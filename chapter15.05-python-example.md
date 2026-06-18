# Recipe 15.5: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the RL concepts from Recipe 15.5. It demonstrates the shape of a ventilator weaning RL system: environment definition, state construction, reward shaping, safety constraints, and offline policy learning. It is not production-ready. Real offline RL for clinical decisions requires extensive validation, IRB approval, and prospective evaluation before any patient-facing deployment. Consider this a learning tool, not a deployment artifact.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `kinesis:GetRecords`, `s3:GetObject`, and `s3:PutObject`.

For the RL training portion, you'll also need SageMaker permissions: `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, and access to an S3 bucket for training data and model artifacts.

---

## Config and Constants

Before the logic, here's the configuration that defines the clinical domain. These constants encode medical knowledge about ventilator weaning: what actions are possible, what's safe, and how to score outcomes. In a real system, these would be developed with intensivists and validated against clinical guidelines.

```python
import numpy as np
import json
import logging
import time
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON format for CloudWatch Logs Insights.
# Never log actual patient identifiers or PHI values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS calls. Adaptive mode handles throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Action Space ---
# These are the discrete actions the RL agent can recommend at each decision point.
# Each maps to a specific ventilator adjustment or clinical action.
# The ordering matters: index 0 is "do nothing," higher indices are more aggressive.
ACTION_SPACE = [
    "maintain_current",       # 0: no change
    "reduce_ps_2",            # 1: reduce pressure support by 2 cmH2O
    "reduce_ps_4",            # 2: reduce pressure support by 4 cmH2O
    "reduce_fio2_5",          # 3: reduce FiO2 by 5 percentage points
    "reduce_fio2_10",         # 4: reduce FiO2 by 10 percentage points
    "reduce_peep_2",          # 5: reduce PEEP by 2 cmH2O
    "initiate_sbt",           # 6: start spontaneous breathing trial
    "recommend_extubation",   # 7: patient ready for extubation
]

# --- State Feature Definitions ---
# The state vector captures the patient's current condition.
# Each feature has a name, expected range (for normalization), and staleness threshold
# (how old a value can be before we flag it as missing).
STATE_FEATURES = [
    # Vital signs (updated every 1-5 minutes from bedside monitors)
    {"name": "heart_rate", "min": 30, "max": 200, "stale_minutes": 15},
    {"name": "spo2", "min": 70, "max": 100, "stale_minutes": 15},
    {"name": "respiratory_rate", "min": 4, "max": 50, "stale_minutes": 15},
    {"name": "map_mmhg", "min": 30, "max": 150, "stale_minutes": 15},
    # Ventilator settings (updated on change)
    {"name": "fio2", "min": 21, "max": 100, "stale_minutes": 30},
    {"name": "peep", "min": 0, "max": 25, "stale_minutes": 30},
    {"name": "pressure_support", "min": 0, "max": 30, "stale_minutes": 30},
    # Lab values (updated every 4-12 hours)
    {"name": "pao2", "min": 40, "max": 500, "stale_minutes": 720},
    {"name": "paco2", "min": 15, "max": 100, "stale_minutes": 720},
    {"name": "ph", "min": 6.8, "max": 7.8, "stale_minutes": 720},
    # Sedation and neurological status
    {"name": "rass_score", "min": -5, "max": 4, "stale_minutes": 60},
    # Contextual (computed, never stale)
    {"name": "hours_on_vent", "min": 0, "max": 720, "stale_minutes": None},
    {"name": "failed_sbt_count", "min": 0, "max": 10, "stale_minutes": None},
    # Trend features (computed over last 4 hours)
    {"name": "spo2_trend", "min": -5, "max": 5, "stale_minutes": None},
    {"name": "rr_trend", "min": -10, "max": 10, "stale_minutes": None},
]

NUM_STATE_FEATURES = len(STATE_FEATURES)
NUM_ACTIONS = len(ACTION_SPACE)

# --- Safety Rules ---
# Hard constraints that override the RL model. These are non-negotiable clinical rules.
# If a recommended action violates any of its required conditions, the action is vetoed.
SAFETY_RULES = {
    "recommend_extubation": [
        {"feature": "rass_score", "operator": ">=", "value": -2},
        {"feature": "fio2", "operator": "<=", "value": 40},
        {"feature": "peep", "operator": "<=", "value": 8},
        {"feature": "spo2", "operator": ">=", "value": 92},
    ],
    "initiate_sbt": [
        {"feature": "fio2", "operator": "<=", "value": 50},
        {"feature": "peep", "operator": "<=", "value": 8},
        {"feature": "rass_score", "operator": ">=", "value": -2},
    ],
    "reduce_fio2_5": [
        {"feature": "spo2", "operator": ">=", "value": 92},
    ],
    "reduce_fio2_10": [
        {"feature": "spo2", "operator": ">=", "value": 94},
    ],
}

# --- Reward Parameters ---
# These weights define what "good" means for the RL agent.
# Developed with clinical input. The exact values are debatable (and should be).
REWARD_CONFIG = {
    "successful_extubation": 1.0,       # terminal reward: patient off vent, stays off
    "failed_extubation": -1.0,          # terminal penalty: reintubated within 48h
    "tracheostomy": -0.5,               # terminal penalty: weaning abandoned
    "death": -2.0,                      # terminal penalty
    "per_hour_on_vent": -0.01,          # small ongoing cost of ventilation
    "desaturation_penalty": -0.1,       # SpO2 drops below 90
    "progress_reward": 0.05,            # vent support decreased
}

# --- AWS Resource Names ---
# In production, these come from environment variables or SSM Parameter Store.
SAGEMAKER_ENDPOINT = "ventilator-weaning-rl-endpoint"
DYNAMODB_TABLE = "ventilator-weaning-episodes"
S3_TRAINING_BUCKET = "ventilator-weaning-training-data"
```

---

## Step 1: State Construction

*Maps to pseudocode Step 1 in the main recipe. Transforms raw clinical data into a normalized state vector suitable for the RL model.*

```python
def normalize_feature(value: float, feature_def: dict) -> float:
    """
    Normalize a raw clinical value to [0, 1] range using the feature's defined bounds.

    Why normalize? RL algorithms work better when all features are on similar scales.
    A heart rate of 80 and an SpO2 of 95 are both "normal," but without normalization
    the model would weight heart rate more heavily simply because it's a larger number.

    Args:
        value: The raw clinical measurement
        feature_def: Dict with 'min' and 'max' defining the expected range

    Returns:
        Value scaled to [0, 1], clipped to bounds
    """
    min_val = feature_def["min"]
    max_val = feature_def["max"]

    # Clip to expected range. Values outside bounds are physiologically extreme
    # and we don't want them distorting the normalization.
    clipped = max(min_val, min(max_val, value))

    # Scale to [0, 1]
    if max_val == min_val:
        return 0.5  # degenerate case, shouldn't happen with real features
    return (clipped - min_val) / (max_val - min_val)

def construct_state_vector(patient_data: dict) -> np.ndarray:
    """
    Build a normalized state vector from raw patient data.

    The input is a dictionary of current clinical values keyed by feature name.
    Missing values are imputed as the midpoint of the expected range (0.5 after
    normalization). In production, you'd use more sophisticated imputation
    (forward-fill from last known value, or a learned imputation model).

    Args:
        patient_data: Dict mapping feature names to current values.
                      Example: {"heart_rate": 82, "spo2": 96, "fio2": 40, ...}

    Returns:
        numpy array of shape (NUM_STATE_FEATURES,) with values in [0, 1]
    """
    state = np.zeros(NUM_STATE_FEATURES, dtype=np.float32)

    for i, feature_def in enumerate(STATE_FEATURES):
        name = feature_def["name"]

        if name in patient_data and patient_data[name] is not None:
            state[i] = normalize_feature(patient_data[name], feature_def)
        else:
            # Missing value: use midpoint as a neutral imputation.
            # This is naive. Production systems forward-fill from the last known
            # value and flag the staleness so the model can learn to be uncertain
            # about stale inputs.
            state[i] = 0.5

    return state
```

---

## Step 2: Safety Filter

*Maps to pseudocode Step 3 in the main recipe. Applies hard clinical constraints that override the RL model's recommendation.*

```python
def check_safety_rule(rule: dict, patient_data: dict) -> bool:
    """
    Evaluate a single safety rule against current patient data.

    Args:
        rule: Dict with 'feature', 'operator', and 'value'
        patient_data: Current clinical values

    Returns:
        True if the rule is satisfied (action is safe), False if violated
    """
    feature_name = rule["feature"]
    threshold = rule["value"]

    # If we don't have the data to evaluate this rule, fail safe (block the action).
    # Better to be conservative than to allow a potentially unsafe action
    # because we're missing information.
    if feature_name not in patient_data or patient_data[feature_name] is None:
        logger.warning(
            "Safety rule check: missing data for '%s', blocking action (fail-safe)",
            feature_name,
        )
        return False

    current_value = patient_data[feature_name]
    operator = rule["operator"]

    if operator == ">=":
        return current_value >= threshold
    elif operator == "<=":
        return current_value <= threshold
    elif operator == ">":
        return current_value > threshold
    elif operator == "<":
        return current_value < threshold
    else:
        # Unknown operator: fail safe
        return False

def apply_safety_filter(
    action_index: int, q_values: np.ndarray, patient_data: dict
) -> tuple[int, bool, str]:
    """
    Check if the recommended action passes safety constraints.
    If not, find the best safe alternative.

    This is the critical safety layer. The RL model optimizes expected reward,
    but it can't guarantee constraint satisfaction. This function provides that
    guarantee by vetoing unsafe recommendations and falling back to the
    highest-Q-value action that passes all safety checks.

    Args:
        action_index: The model's recommended action (index into ACTION_SPACE)
        q_values: Q-values for all actions (from the model)
        patient_data: Current clinical values for rule evaluation

    Returns:
        Tuple of (safe_action_index, was_overridden, override_reason)
    """
    action_name = ACTION_SPACE[action_index]

    # Check if this action has safety rules
    if action_name in SAFETY_RULES:
        for rule in SAFETY_RULES[action_name]:
            if not check_safety_rule(rule, patient_data):
                # Safety violation. Find the best alternative.
                reason = (
                    f"Blocked '{action_name}': {rule['feature']} "
                    f"must be {rule['operator']} {rule['value']}"
                )
                logger.info("Safety override: %s", reason)

                # Try actions in order of Q-value (best to worst),
                # skipping any that also fail safety checks.
                sorted_actions = np.argsort(q_values)[::-1]  # descending Q-value
                for alt_index in sorted_actions:
                    alt_name = ACTION_SPACE[int(alt_index)]
                    if alt_name == action_name:
                        continue  # skip the one we just blocked

                    # Check if this alternative passes its own safety rules
                    if alt_name in SAFETY_RULES:
                        alt_safe = all(
                            check_safety_rule(r, patient_data)
                            for r in SAFETY_RULES[alt_name]
                        )
                        if not alt_safe:
                            continue  # this alternative is also unsafe

                    # Found a safe alternative
                    return int(alt_index), True, reason

                # If nothing passes, fall back to "maintain_current" (always safe)
                return 0, True, reason

    # No safety rules for this action, or all rules passed
    return action_index, False, ""
```

---

## Step 3: Reward Computation

*Maps to pseudocode Step 5 in the main recipe. Defines how outcomes translate into the reward signal the RL agent learns from.*

```python
def compute_step_reward(
    prev_state: dict, current_state: dict, action_taken: str
) -> float:
    """
    Compute the intermediate reward for a single time step.

    This is called at each decision point during an episode. It provides
    the "shaping" signal that guides learning between the sparse terminal
    rewards (extubation success/failure). Without step rewards, the agent
    only learns from episode endings, which makes learning very slow.

    The reward design encodes clinical values:
    - Time on vent is bad (complications accumulate)
    - Desaturation is bad (patient is struggling)
    - Reducing support is good (progress toward independence)

    Args:
        prev_state: Patient data at the previous time step
        current_state: Patient data at the current time step
        action_taken: The action that was executed (string from ACTION_SPACE)

    Returns:
        Float reward value for this time step
    """
    reward = 0.0

    # Penalty for each hour on the ventilator.
    # This creates urgency: the agent learns that keeping a patient on the vent
    # has a cost, even if nothing bad happens. Without this, the agent might
    # learn an overly conservative "never extubate" policy.
    time_step_hours = 4.0  # assuming 4-hour decision intervals
    reward += REWARD_CONFIG["per_hour_on_vent"] * time_step_hours

    # Penalty for desaturation events.
    # SpO2 below 90 is clinically concerning. This teaches the agent that
    # aggressive weaning that causes desaturation is not free.
    if current_state.get("spo2") is not None and current_state["spo2"] < 90:
        reward += REWARD_CONFIG["desaturation_penalty"]

    # Reward for making progress (reducing ventilator support).
    # Only awarded if the patient tolerated the reduction (SpO2 stayed above 92).
    progress_actions = {"reduce_ps_2", "reduce_ps_4", "reduce_fio2_5", "reduce_fio2_10", "reduce_peep_2"}
    if action_taken in progress_actions:
        if current_state.get("spo2") is not None and current_state["spo2"] >= 92:
            reward += REWARD_CONFIG["progress_reward"]

    return reward

def compute_terminal_reward(episode_outcome: str) -> float:
    """
    Compute the terminal reward when an episode ends.

    An episode ends when the patient is extubated (successfully or not),
    transitions to tracheostomy, dies, or is discharged.

    Args:
        episode_outcome: One of "successful_extubation", "failed_extubation",
                         "tracheostomy", "death"

    Returns:
        Float terminal reward
    """
    if episode_outcome in REWARD_CONFIG:
        return REWARD_CONFIG[episode_outcome]

    logger.warning("Unknown episode outcome: '%s', returning 0 reward", episode_outcome)
    return 0.0
```

---

## Step 4: Policy Inference (SageMaker Endpoint)

*Maps to pseudocode Step 2 in the main recipe. Calls the trained RL model to get action recommendations.*

```python
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)

def get_policy_recommendation(state_vector: np.ndarray) -> dict:
    """
    Call the SageMaker endpoint hosting the trained RL policy.

    The endpoint runs the trained Q-network: given a state vector, it returns
    Q-values for each possible action. The action with the highest Q-value
    is the model's recommendation.

    In production, the endpoint would be an ml.m5.large or similar instance
    running the trained model. For this example, we show the API call pattern.

    Args:
        state_vector: Normalized state array of shape (NUM_STATE_FEATURES,)

    Returns:
        Dict with 'action_index', 'action_name', 'q_values', and 'confidence'
    """
    # Serialize the state vector as JSON for the endpoint.
    # SageMaker endpoints accept various content types; JSON is simplest for debugging.
    payload = json.dumps({"state": state_vector.tolist()})

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=payload,
    )

    # Parse the model's response. Expected format:
    # {"q_values": [0.12, 0.45, 0.38, ...]}  (one value per action)
    result = json.loads(response["Body"].read().decode("utf-8"))
    q_values = np.array(result["q_values"], dtype=np.float32)

    # Select the action with the highest Q-value
    action_index = int(np.argmax(q_values))

    # Confidence: how much better is the best action vs. the runner-up?
    # High confidence means one action clearly dominates.
    # Low confidence means multiple actions look similarly good.
    sorted_q = np.sort(q_values)[::-1]
    if abs(sorted_q[0]) > 1e-8:
        confidence = (sorted_q[0] - sorted_q[1]) / abs(sorted_q[0])
    else:
        confidence = 0.0

    return {
        "action_index": action_index,
        "action_name": ACTION_SPACE[action_index],
        "q_values": q_values,
        "confidence": float(confidence),
    }
```

---

## Step 5: Episode Logging (DynamoDB)

*Maps to pseudocode Step 4 in the main recipe. Logs every recommendation and decision for audit and future retraining.*

```python
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
episode_table = dynamodb.Table(DYNAMODB_TABLE)

def log_recommendation(
    patient_id: str,
    episode_id: str,
    timestamp: str,
    state_vector: np.ndarray,
    recommendation: dict,
    safety_override: bool,
    override_reason: str,
) -> None:
    """
    Write a recommendation event to the episode log in DynamoDB.

    Every recommendation the model makes is logged, whether the clinician
    follows it or not. This creates the training data for future model iterations.
    The clinician's actual decision gets appended later (via update_with_clinician_action).

    DynamoDB schema:
        PK: patient_id
        SK: episode_id#timestamp
        Attributes: state, recommendation, safety info, model version

    Args:
        patient_id: Patient identifier (de-identified in non-production)
        episode_id: Unique ID for this weaning episode
        timestamp: ISO 8601 timestamp of the recommendation
        state_vector: The state that produced this recommendation
        recommendation: Output from get_policy_recommendation
        safety_override: Whether the safety filter changed the recommendation
        override_reason: Why the override happened (empty string if no override)
    """
    # DynamoDB requires Decimal for numbers, not float.
    # This is a known boto3 gotcha that will throw TypeError if you forget.
    item = {
        "patient_id": patient_id,
        "sort_key": f"{episode_id}#{timestamp}",
        "episode_id": episode_id,
        "timestamp": timestamp,
        "state_vector": json.dumps(state_vector.tolist()),
        "recommended_action": recommendation["action_name"],
        "recommended_action_index": recommendation["action_index"],
        "q_values": json.dumps([float(q) for q in recommendation["q_values"]]),
        "confidence": Decimal(str(round(recommendation["confidence"], 4))),
        "safety_override": safety_override,
        "override_reason": override_reason,
        "model_version": "v1.0",  # track which model produced this
        # clinician_action and outcome will be filled in later
        "clinician_action": None,
        "step_reward": None,
    }

    episode_table.put_item(Item=item)
    logger.info(
        "Logged recommendation for patient %s: %s (confidence: %.2f, override: %s)",
        patient_id,
        recommendation["action_name"],
        recommendation["confidence"],
        safety_override,
    )
```

---

## Step 6: Training Data Preparation

*This step prepares historical episodes for offline RL training. It transforms logged episodes into the (state, action, reward, next_state, done) tuples that offline RL algorithms consume.*

```python
def prepare_training_batch(episodes: list[dict]) -> dict:
    """
    Convert a batch of completed episodes into training data for offline RL.

    Each episode is a sequence of (state, action, reward, next_state, done) tuples.
    This is the standard format for batch RL algorithms like Conservative Q-Learning (CQL)
    or Batch-Constrained Q-Learning (BCQ).

    The key insight of offline RL: we learn from what clinicians actually did,
    not from what the model would have done. The training data contains the
    clinician's actions and the resulting patient trajectories.

    Args:
        episodes: List of completed episode dicts, each containing a list of
                  time steps with state, action, reward, and outcome info.

    Returns:
        Dict with numpy arrays: 'states', 'actions', 'rewards', 'next_states', 'dones'
    """
    states = []
    actions = []
    rewards = []
    next_states = []
    dones = []

    for episode in episodes:
        steps = episode["steps"]
        terminal_reward = compute_terminal_reward(episode["outcome"])

        for i, step in enumerate(steps):
            state = np.array(step["state_vector"], dtype=np.float32)
            action = ACTION_SPACE.index(step["clinician_action"])

            is_terminal = (i == len(steps) - 1)

            if is_terminal:
                # Last step: add terminal reward
                reward = step.get("step_reward", 0.0) + terminal_reward
                next_state = np.zeros_like(state)  # terminal state
                done = True
            else:
                reward = step.get("step_reward", 0.0)
                next_state = np.array(steps[i + 1]["state_vector"], dtype=np.float32)
                done = False

            states.append(state)
            actions.append(action)
            rewards.append(reward)
            next_states.append(next_state)
            dones.append(done)

    return {
        "states": np.array(states, dtype=np.float32),
        "actions": np.array(actions, dtype=np.int32),
        "rewards": np.array(rewards, dtype=np.float32),
        "next_states": np.array(next_states, dtype=np.float32),
        "dones": np.array(dones, dtype=np.bool_),
    }
```

---

## Step 7: Offline RL Training (Conservative Q-Learning)

*This demonstrates the core CQL training loop. In production, this runs as a SageMaker training job. Here we show the algorithm logic so you understand what's happening inside the training container.*

```python
def train_cql_policy(training_data: dict, num_iterations: int = 1000) -> dict:
    """
    Train a Conservative Q-Learning (CQL) policy from offline data.

    CQL is the standard choice for healthcare offline RL because it's conservative:
    it penalizes Q-values for actions that weren't observed in the training data.
    This prevents the learned policy from recommending actions we have no evidence about,
    which is critical in a clinical setting.

    The core idea: standard Q-learning can overestimate Q-values for out-of-distribution
    actions (actions the clinicians never took). CQL adds a regularization term that
    pushes down Q-values for actions not seen in the data, while pushing up Q-values
    for actions that were actually taken. The result is a policy that stays close to
    observed clinical practice while still finding improvements.

    This is a simplified version. Production CQL uses neural networks for the Q-function,
    target networks for stability, and careful hyperparameter tuning.

    Args:
        training_data: Output from prepare_training_batch
        num_iterations: Number of training iterations

    Returns:
        Dict representing the trained Q-table (state discretization for simplicity)
    """
    states = training_data["states"]
    actions = training_data["actions"]
    rewards = training_data["rewards"]
    next_states = training_data["next_states"]
    dones = training_data["dones"]

    # For this example, we use a tabular Q-function with state discretization.
    # Production systems use neural network Q-functions (Deep CQL).
    # The discretization bins each normalized feature into a small number of levels.
    num_bins = 5
    num_discrete_states = num_bins ** min(NUM_STATE_FEATURES, 4)  # limit for tractability

    def discretize_state(state: np.ndarray) -> int:
        """Convert continuous state to discrete bin index (simplified)."""
        # Use first 4 features for discretization (SpO2, FiO2, PEEP, PS)
        key_indices = [1, 4, 5, 6]  # spo2, fio2, peep, pressure_support
        bins = np.clip((state[key_indices] * num_bins).astype(int), 0, num_bins - 1)
        index = 0
        for b in bins:
            index = index * num_bins + b
        return index % num_discrete_states

    # Initialize Q-table
    q_table = np.zeros((num_discrete_states, NUM_ACTIONS), dtype=np.float64)

    # CQL hyperparameters
    learning_rate = 0.1
    discount_factor = 0.99
    cql_alpha = 1.0  # CQL regularization strength (higher = more conservative)

    logger.info("Starting CQL training: %d iterations, %d transitions", num_iterations, len(states))

    for iteration in range(num_iterations):
        # Sample a random mini-batch from the training data
        batch_size = min(64, len(states))
        indices = np.random.choice(len(states), size=batch_size, replace=False)

        for idx in indices:
            s = discretize_state(states[idx])
            a = actions[idx]
            r = rewards[idx]
            done = dones[idx]

            if done:
                target = r
            else:
                ns = discretize_state(next_states[idx])
                target = r + discount_factor * np.max(q_table[ns])

            # Standard Q-learning update
            td_error = target - q_table[s, a]
            q_table[s, a] += learning_rate * td_error

            # CQL regularization: push down Q-values for all actions,
            # then push up the Q-value for the action actually taken.
            # Net effect: actions seen in data keep their values,
            # unseen actions get penalized.
            q_table[s] -= learning_rate * cql_alpha * (q_table[s] - q_table[s].mean())
            q_table[s, a] += learning_rate * cql_alpha * 0.5

        if (iteration + 1) % 200 == 0:
            mean_q = q_table[q_table != 0].mean() if np.any(q_table != 0) else 0
            logger.info("  Iteration %d/%d, mean Q-value: %.3f", iteration + 1, num_iterations, mean_q)

    logger.info("CQL training complete.")
    return {"q_table": q_table, "num_bins": num_bins, "discretize_fn": discretize_state}
```

---

## Putting It All Together

Here's the full inference pipeline assembled into a single function. This is what runs when a new patient state arrives and the system needs to produce a recommendation.

```python
def generate_weaning_recommendation(patient_id: str, patient_data: dict, episode_id: str) -> dict:
    """
    Run the full ventilator weaning RL pipeline for one decision point.

    This is the main entry point for real-time inference. It takes the current
    patient state, runs it through the RL model, applies safety constraints,
    and logs the recommendation.

    Args:
        patient_id: Patient identifier
        patient_data: Dict of current clinical values (raw, unnormalized)
                      Example: {"heart_rate": 82, "spo2": 96, "fio2": 40, ...}
        episode_id: Unique ID for this weaning episode

    Returns:
        Dict with the final recommendation, safety info, and confidence
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Step 1: Construct normalized state vector from raw clinical data
    print(f"[1/4] Constructing state vector for patient {patient_id}")
    state_vector = construct_state_vector(patient_data)
    print(f"       State vector: {state_vector.shape[0]} features, "
          f"mean={state_vector.mean():.3f}")

    # Step 2: Get RL model recommendation
    print(f"[2/4] Querying RL policy endpoint: {SAGEMAKER_ENDPOINT}")
    recommendation = get_policy_recommendation(state_vector)
    print(f"       Raw recommendation: {recommendation['action_name']} "
          f"(confidence: {recommendation['confidence']:.2f})")

    # Step 3: Apply safety filter
    print(f"[3/4] Applying safety constraints")
    safe_action_index, was_overridden, override_reason = apply_safety_filter(
        recommendation["action_index"],
        recommendation["q_values"],
        patient_data,
    )

    if was_overridden:
        print(f"       SAFETY OVERRIDE: {override_reason}")
        print(f"       Fallback action: {ACTION_SPACE[safe_action_index]}")
        final_action = ACTION_SPACE[safe_action_index]
    else:
        print(f"       Safety check: PASSED")
        final_action = recommendation["action_name"]

    # Step 4: Log the recommendation
    print(f"[4/4] Logging recommendation to DynamoDB")
    log_recommendation(
        patient_id=patient_id,
        episode_id=episode_id,
        timestamp=timestamp,
        state_vector=state_vector,
        recommendation=recommendation,
        safety_override=was_overridden,
        override_reason=override_reason,
    )

    result = {
        "patient_id": patient_id,
        "timestamp": timestamp,
        "recommended_action": final_action,
        "model_raw_recommendation": recommendation["action_name"],
        "confidence": recommendation["confidence"],
        "safety_override": was_overridden,
        "override_reason": override_reason,
        "q_values": {ACTION_SPACE[i]: float(q) for i, q in enumerate(recommendation["q_values"])},
    }

    print(f"\nFinal recommendation: {final_action}")
    print(json.dumps(result, indent=2, default=str))
    return result

# --- Example usage ---
if __name__ == "__main__":
    # Simulated patient data (what you'd get from the EHR/ventilator in real time)
    sample_patient = {
        "heart_rate": 82,
        "spo2": 96,
        "respiratory_rate": 18,
        "map_mmhg": 72,
        "fio2": 40,
        "peep": 5,
        "pressure_support": 10,
        "pao2": 95,
        "paco2": 38,
        "ph": 7.38,
        "rass_score": -1,
        "hours_on_vent": 72,
        "failed_sbt_count": 0,
        "spo2_trend": 0.5,   # slightly improving
        "rr_trend": -0.2,    # stable
    }

    result = generate_weaning_recommendation(
        patient_id="ICU-2026-04821",
        patient_data=sample_patient,
        episode_id="EP-2026-04821-001",
    )
```

---

## The Gap Between This and Production

This example demonstrates the architecture and logic of an RL-based ventilator weaning system. Here's the substantial distance between this code and something you'd deploy in a clinical setting:

**Offline RL algorithm.** The tabular CQL shown here is pedagogical. Production systems use deep neural network Q-functions (Deep CQL or BCQ) trained on thousands of patient episodes. You'd use a framework like d3rlpy, RLlib, or a custom PyTorch implementation running on SageMaker training jobs with GPU instances.

**State representation.** Real ICU state construction is far more complex than a flat feature vector. You need temporal features (trends over multiple windows), handling of irregular time series (vitals every 5 min, labs every 6 hours), learned embeddings for categorical variables (diagnosis codes, vent modes), and attention mechanisms for variable-length histories.

**Off-policy evaluation.** Before deploying any learned policy, you must evaluate it using importance sampling, doubly robust estimators, or fitted Q-evaluation on held-out patient episodes. This code doesn't include OPE. Without it, you have no idea whether the learned policy is better or worse than current clinical practice.

**Data pipeline.** Real-time state construction requires a streaming pipeline (Kinesis, Lambda) that handles HL7/FHIR messages from the EHR, ventilator data feeds, and lab interfaces. The data arrives asynchronously, with different latencies and formats. Aligning these into a coherent state snapshot is a significant engineering challenge.

**Model versioning and A/B testing.** Production systems need model registry (SageMaker Model Registry), shadow mode deployment (model runs but recommendations aren't shown), and gradual rollout with monitoring. You never flip a switch from "old model" to "new model" overnight.

**Clinician interface.** The recommendation needs to be presented in a way that's useful, not distracting. This means integration with the EHR (Epic, Cerner), appropriate alerting thresholds (don't alert for "maintain current"), and clear explanations of why the model is recommending what it is.

**IRB and regulatory.** Any system that influences clinical decisions requires Institutional Review Board approval, likely a prospective validation study, and potentially FDA clearance depending on how it's deployed. The regulatory pathway for RL-based clinical decision support is still evolving.

**Error handling and monitoring.** Every AWS call needs try/except with specific handling for throttling, timeouts, and service errors. The SageMaker endpoint needs health checks, auto-scaling, and latency monitoring. Model drift detection (is the patient population changing in ways the model wasn't trained for?) needs continuous monitoring via CloudWatch.

**Encryption and access control.** All patient data in DynamoDB, S3, and Kinesis must be encrypted with KMS customer-managed keys. IAM policies must follow least-privilege. VPC endpoints keep all traffic off the public internet. CloudTrail logs every API call for audit.

**Testing.** This code has no tests. Production needs unit tests for state construction and safety filtering, integration tests against the SageMaker endpoint, simulation tests that run the policy against synthetic patient trajectories, and regression tests that verify safety constraints are never violated.

**The fundamental gap.** This code shows you how the pieces fit together. The real work in clinical RL is not the code. It's the clinical validation, the data quality, the reward design (which encodes clinical values that reasonable people disagree about), and the trust-building with clinicians who will ultimately decide whether to follow the recommendations. The engineering is maybe 30% of the effort. The clinical science and organizational change management are the other 70%.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 15.5](chapter15.05-ventilator-weaning-protocols) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
