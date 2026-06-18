# Recipe 15.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the sepsis treatment optimization system from Recipe 15.4. It demonstrates offline reinforcement learning (Conservative Q-Learning) with safety constraints using numpy for the core RL logic and boto3 for AWS integration. This is absolutely not production-ready. A real sepsis RL system requires years of validation, IRB approval, prospective studies, and likely FDA clearance before it touches a patient. Think of this as a learning tool for understanding the mechanics of offline RL in healthcare, not something you'd deploy to an ICU.

---

## Setup

```bash
pip install boto3 numpy
```

Your environment needs credentials configured with permissions for `s3:GetObject`, `s3:PutObject`, `sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, and `cloudwatch:PutMetricData`. You'll need a signed BAA because even de-identified ICU trajectory data is treated as PHI in most institutional policies.

---

## Configuration and Constants

These define the sepsis MDP (Markov Decision Process) parameters. The action discretization bins, state features, and reward structure are all clinical decisions that should be made with intensivists, not by an engineer alone. The values here follow the standard formulation from Komorowski et al. (2018) and subsequent literature.

```python
import json
import time
import uuid
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import boto3
import numpy as np
from botocore.config import Config

# ============================================================================
# MDP CONFIGURATION
# ============================================================================
# These parameters define the sepsis treatment MDP. The action bins are based
# on clinical practice patterns (not arbitrary quantiles). The state features
# are the standard set from the sepsis RL literature. Changing these requires
# retraining the entire policy.

# Action space: 5 fluid levels x 5 vasopressor levels = 25 discrete actions.
# Each bin boundary represents a clinically meaningful threshold.
FLUID_BINS_ML = [0, 250, 500, 1000, 2000]  # mL per 4-hour window
# 0: no fluids
# 250: minimal maintenance
# 500: moderate resuscitation
# 1000: aggressive resuscitation
# 2000+: very aggressive bolus

VASOPRESSOR_BINS_MCG = [0.0, 0.08, 0.16, 0.28, 0.45]  # norepinephrine equiv mcg/kg/min
# 0: no vasopressors
# 0.08: low-dose support
# 0.16: moderate support
# 0.28: high-dose support
# 0.45+: maximal support

NUM_FLUID_LEVELS = 5
NUM_VASO_LEVELS = 5
NUM_ACTIONS = NUM_FLUID_LEVELS * NUM_VASO_LEVELS  # 25

# State features: the physiological variables we track at each 4-hour time step.
# Order matters because the neural network expects a fixed input shape.
STATE_FEATURES = [
    "heart_rate",
    "mean_arterial_pressure",
    "temperature",
    "respiratory_rate",
    "spo2",
    "lactate",
    "creatinine",
    "bilirubin",
    "platelet_count",
    "wbc",
    "ph",
    "pao2_fio2_ratio",
    "urine_output_4h",
    "cumulative_fluid_balance",
    "gcs_score",
    "sofa_score",
    "hours_since_admission",
    "age",
]
STATE_DIM = len(STATE_FEATURES)

# Reward configuration.
# Terminal rewards are large to dominate the cumulative sum.
# Intermediate rewards provide denser signal during training.
REWARD_CONFIG = {
    "survival_reward": 15.0,
    "death_penalty": -15.0,
    "sofa_improvement_bonus": 0.5,   # per point of SOFA decrease
    "sofa_worsening_penalty": -0.5,  # per point of SOFA increase
    "lactate_clearance_bonus": 0.25, # per mmol/L decrease in lactate
}

# Training hyperparameters for Conservative Q-Learning.
CQL_CONFIG = {
    "gamma": 0.99,              # discount factor (high because we care about survival)
    "learning_rate": 3e-4,
    "batch_size": 256,
    "num_iterations": 50000,
    "cql_alpha": 2.0,           # conservatism weight (higher = stays closer to clinician behavior)
    "target_update_freq": 100,  # sync target network every N iterations
    "tau": 0.005,               # soft update coefficient
    "hidden_dims": [256, 256],  # Q-network hidden layer sizes
}

# Safety constraint thresholds. These are hard limits that override the policy.
SAFETY_CONSTRAINTS = {
    "min_map_for_no_vasopressors": 55,       # mmHg
    "max_fluid_balance_for_max_fluids": 6000, # mL
    "min_sofa_for_zero_treatment": 6,
    "lactate_rising_vaso_floor": 3,           # don't reduce vaso below level 3 if lactate rising
}

# AWS resource configuration
S3_BUCKET = "sepsis-rl-trajectories"
MODEL_ARTIFACT_PREFIX = "models/"
TRAJECTORY_PREFIX = "trajectories/"
POLICY_TABLE = "sepsis-rl-policy-lookup"
AUDIT_TABLE = "sepsis-rl-recommendation-audit"

# boto3 retry configuration for resilience under load
BOTO3_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
```

---

## Step 1: Trajectory Construction

*Maps to pseudocode Step 1 in the main recipe. This takes raw patient time-series data and constructs the (state, action, reward, next_state) tuples that the RL algorithm learns from.*

```python
def discretize_action(iv_fluid_ml: float, vasopressor_dose: float) -> int:
    """
    Map continuous treatment values to a discrete action ID (0-24).

    The action space is a 5x5 grid: 5 fluid levels x 5 vasopressor levels.
    Action ID = fluid_level * 5 + vaso_level.

    Args:
        iv_fluid_ml: Total IV fluid administered in this 4-hour window (mL).
        vasopressor_dose: Max norepinephrine-equivalent dose (mcg/kg/min).

    Returns:
        Integer action ID from 0 to 24.
    """
    # Find which bin the fluid volume falls into.
    # np.digitize returns the index of the bin: 0 means below first threshold,
    # len(bins) means above the last threshold. Values at bin edges go into the
    # higher bin (right=False default), so 250 mL maps to level 1 ("minimal maintenance").
    fluid_level = int(np.digitize(iv_fluid_ml, FLUID_BINS_ML)) - 1
    fluid_level = max(0, min(fluid_level, NUM_FLUID_LEVELS - 1))

    vaso_level = int(np.digitize(vasopressor_dose, VASOPRESSOR_BINS_MCG)) - 1
    vaso_level = max(0, min(vaso_level, NUM_VASO_LEVELS - 1))

    return fluid_level * NUM_VASO_LEVELS + vaso_level

def decode_action(action_id: int) -> Tuple[int, int]:
    """
    Reverse of discretize_action: given an action ID, return (fluid_level, vaso_level).
    """
    fluid_level = action_id // NUM_VASO_LEVELS
    vaso_level = action_id % NUM_VASO_LEVELS
    return fluid_level, vaso_level

def compute_reward(
    current_sofa: float,
    next_sofa: float,
    current_lactate: float,
    next_lactate: float,
    is_terminal: bool,
    survived: bool,
) -> float:
    """
    Compute the reward for a single transition.

    Combines terminal outcome (survival/death) with intermediate signals
    (SOFA score changes, lactate clearance). The terminal reward dominates
    the cumulative sum, but intermediate rewards help the algorithm learn
    which actions lead toward improvement vs. deterioration.

    Args:
        current_sofa: SOFA score at current time step.
        next_sofa: SOFA score at next time step.
        current_lactate: Lactate at current time step (mmol/L).
        next_lactate: Lactate at next time step (mmol/L).
        is_terminal: Whether this is the last time step for this patient.
        survived: Whether the patient survived (only meaningful if is_terminal).

    Returns:
        Float reward value.
    """
    reward = 0.0

    if is_terminal:
        # Terminal reward: the big signal.
        reward += REWARD_CONFIG["survival_reward"] if survived else REWARD_CONFIG["death_penalty"]
    else:
        # Intermediate rewards: SOFA improvement/worsening.
        sofa_change = current_sofa - next_sofa  # positive = improvement
        if sofa_change > 0:
            reward += sofa_change * REWARD_CONFIG["sofa_improvement_bonus"]
        elif sofa_change < 0:
            reward += abs(sofa_change) * REWARD_CONFIG["sofa_worsening_penalty"]

        # Lactate clearance bonus.
        lactate_change = current_lactate - next_lactate  # positive = clearance
        if lactate_change > 0:
            reward += lactate_change * REWARD_CONFIG["lactate_clearance_bonus"]

    return reward

def build_trajectory(patient_data: Dict) -> List[Dict]:
    """
    Convert a single patient's time-series data into a trajectory of
    (state, action, reward, next_state) tuples.

    Args:
        patient_data: Dictionary with keys:
            - "time_steps": list of dicts, each containing state features + treatment info
            - "survived": bool indicating 90-day survival
            - "patient_id": anonymized identifier

    Returns:
        List of transition dicts, each with keys: state, action, reward, next_state, done.
    """
    time_steps = patient_data["time_steps"]
    survived = patient_data["survived"]
    trajectory = []

    for t in range(len(time_steps) - 1):
        current = time_steps[t]
        next_step = time_steps[t + 1]
        is_terminal = (t == len(time_steps) - 2)

        # Construct state vector: extract features in the canonical order.
        state = np.array([current.get(f, 0.0) for f in STATE_FEATURES], dtype=np.float32)
        next_state = np.array([next_step.get(f, 0.0) for f in STATE_FEATURES], dtype=np.float32)

        # Discretize the treatment action.
        action = discretize_action(
            iv_fluid_ml=current.get("iv_fluid_ml", 0.0),
            vasopressor_dose=current.get("vasopressor_dose", 0.0),
        )

        # Compute reward for this transition.
        reward = compute_reward(
            current_sofa=current.get("sofa_score", 0.0),
            next_sofa=next_step.get("sofa_score", 0.0),
            current_lactate=current.get("lactate", 0.0),
            next_lactate=next_step.get("lactate", 0.0),
            is_terminal=is_terminal,
            survived=survived,
        )

        trajectory.append({
            "state": state,
            "action": action,
            "reward": reward,
            "next_state": next_state,
            "done": is_terminal,
        })

    return trajectory
```

---

## Step 2: Q-Network Definition

*This implements the neural network that estimates Q-values (expected cumulative reward for each state-action pair). Two networks are used: the "online" network that gets updated, and a "target" network that provides stable training targets.*

```python
class QNetwork:
    """
    A simple feedforward neural network for Q-value estimation.

    Takes a state vector as input, outputs Q-values for all 25 actions.
    Uses numpy for clarity (a real implementation would use PyTorch or TensorFlow
    for GPU acceleration and automatic differentiation).

    This is intentionally simplified. A production implementation would use
    a proper deep learning framework. We use numpy here so you can see
    exactly what's happening at each step without framework abstractions.
    """

    def __init__(self, state_dim: int, num_actions: int, hidden_dims: List[int], lr: float):
        """
        Initialize network weights with Xavier initialization.

        Args:
            state_dim: Number of input features (18 for our state representation).
            num_actions: Number of output Q-values (25 for our action space).
            hidden_dims: List of hidden layer sizes, e.g. [256, 256].
            lr: Learning rate for gradient descent.
        """
        self.lr = lr
        self.layers = []

        # Build layer dimensions: input -> hidden1 -> hidden2 -> output
        dims = [state_dim] + hidden_dims + [num_actions]

        for i in range(len(dims) - 1):
            # Xavier initialization: scale weights by sqrt(2 / (fan_in + fan_out)).
            # This prevents vanishing/exploding gradients in deep networks.
            scale = np.sqrt(2.0 / (dims[i] + dims[i + 1]))
            W = np.random.randn(dims[i], dims[i + 1]).astype(np.float32) * scale
            b = np.zeros(dims[i + 1], dtype=np.float32)
            self.layers.append((W, b))

    def forward(self, state: np.ndarray) -> np.ndarray:
        """
        Forward pass: compute Q-values for all actions given a state.

        Args:
            state: Shape (state_dim,) or (batch_size, state_dim).

        Returns:
            Q-values with shape (num_actions,) or (batch_size, num_actions).
        """
        x = state
        for i, (W, b) in enumerate(self.layers):
            x = x @ W + b
            # ReLU activation for all layers except the last (output is unbounded Q-values).
            if i < len(self.layers) - 1:
                x = np.maximum(0, x)
        return x

    def get_q_value(self, state: np.ndarray, action: int) -> float:
        """Get Q-value for a specific state-action pair."""
        q_values = self.forward(state)
        if q_values.ndim == 1:
            return float(q_values[action])
        return float(q_values[:, action])

    def copy_from(self, other: "QNetwork"):
        """Hard copy weights from another network."""
        for i in range(len(self.layers)):
            self.layers[i] = (
                other.layers[i][0].copy(),
                other.layers[i][1].copy(),
            )

    def soft_update_from(self, other: "QNetwork", tau: float):
        """
        Soft update: blend this network's weights toward another network's weights.
        target = tau * online + (1 - tau) * target

        This provides more stable training targets than hard copies.
        """
        for i in range(len(self.layers)):
            W_self, b_self = self.layers[i]
            W_other, b_other = other.layers[i]
            new_W = tau * W_other + (1 - tau) * W_self
            new_b = tau * b_other + (1 - tau) * b_self
            self.layers[i] = (new_W, new_b)
```

---

## Step 3: Safety Constraint Layer

*Maps to pseudocode Step 4 in the main recipe. These are hard clinical boundaries that override the learned policy. No matter what the Q-function says, these constraints cannot be violated.*

```python
def apply_safety_constraints(state: np.ndarray, q_values: np.ndarray) -> np.ndarray:
    """
    Apply clinical safety constraints by masking out dangerous actions.

    Returns a modified Q-values array where unsafe actions have been set to
    negative infinity (so they'll never be selected by argmax).

    The constraints encode domain knowledge that should never be violated:
    - Severely hypotensive patients must have vasopressor support
    - Fluid-overloaded patients shouldn't get maximum fluids
    - Deteriorating patients shouldn't have support withdrawn
    - Critically ill patients need active treatment

    Args:
        state: The current patient state vector (shape: STATE_DIM).
        q_values: Q-values for all 25 actions (shape: NUM_ACTIONS).

    Returns:
        Masked Q-values with unsafe actions set to -inf.
    """
    masked_q = q_values.copy()

    # Extract relevant state features by index.
    # These indices match the STATE_FEATURES list order.
    map_idx = STATE_FEATURES.index("mean_arterial_pressure")
    fluid_balance_idx = STATE_FEATURES.index("cumulative_fluid_balance")
    lactate_idx = STATE_FEATURES.index("lactate")
    sofa_idx = STATE_FEATURES.index("sofa_score")

    map_value = state[map_idx]
    fluid_balance = state[fluid_balance_idx]
    sofa_score = state[sofa_idx]

    # Constraint 1: If MAP < 55, cannot have zero vasopressors.
    # MAP below 55 is associated with acute organ injury. The policy must not
    # remove hemodynamic support at this level.
    if map_value < SAFETY_CONSTRAINTS["min_map_for_no_vasopressors"]:
        for action_id in range(NUM_ACTIONS):
            _, vaso_level = decode_action(action_id)
            if vaso_level == 0:
                masked_q[action_id] = -np.inf

    # Constraint 2: If fluid balance > 6000 mL, cannot give max fluids.
    # Fluid overload causes pulmonary edema and worsens outcomes.
    if fluid_balance > SAFETY_CONSTRAINTS["max_fluid_balance_for_max_fluids"]:
        for action_id in range(NUM_ACTIONS):
            fluid_level, _ = decode_action(action_id)
            if fluid_level == NUM_FLUID_LEVELS - 1:
                masked_q[action_id] = -np.inf

    # Constraint 3: If SOFA >= 6, cannot have zero treatment (action 0 = no fluids, no vaso).
    # SOFA >= 6 indicates significant organ dysfunction requiring active management.
    if sofa_score >= SAFETY_CONSTRAINTS["min_sofa_for_zero_treatment"]:
        masked_q[0] = -np.inf

    # Note: Constraint 3 from the main recipe (lactate rising + high vaso -> don't reduce)
    # requires access to the previous state to compute lactate trend. In production,
    # include lactate_trend as a derived state feature or pass previous state to this function.

    # Fallback: if all actions are masked, unmask the most conservative non-zero action.
    # This shouldn't happen with well-designed constraints, but defensive coding matters
    # when patient safety is on the line.
    if np.all(np.isinf(masked_q) & (masked_q < 0)):
        # Default to moderate fluids + moderate vasopressors (action 12: fluid=2, vaso=2)
        masked_q[12] = 0.0

    return masked_q
```

---

## Step 4: Conservative Q-Learning Training

*Maps to pseudocode Step 3 in the main recipe. This is the core offline RL algorithm. CQL adds a penalty that discourages the Q-function from overestimating the value of actions that are rare in the training data. This is critical for healthcare: if clinicians rarely took a particular action, we should be skeptical that it's secretly optimal.*

```python
class ReplayBuffer:
    """
    Stores all training trajectories for batch sampling.

    In offline RL, the buffer is fixed (no new data is added during training).
    We load all historical trajectories once and sample from them repeatedly.
    """

    def __init__(self):
        self.states = []
        self.actions = []
        self.rewards = []
        self.next_states = []
        self.dones = []

    def add_trajectory(self, trajectory: List[Dict]):
        """Add all transitions from a single patient trajectory."""
        for transition in trajectory:
            self.states.append(transition["state"])
            self.actions.append(transition["action"])
            self.rewards.append(transition["reward"])
            self.next_states.append(transition["next_state"])
            self.dones.append(transition["done"])

    def sample(self, batch_size: int) -> Tuple:
        """Sample a random batch of transitions for training."""
        indices = np.random.randint(0, len(self.states), size=batch_size)
        return (
            np.array([self.states[i] for i in indices]),
            np.array([self.actions[i] for i in indices]),
            np.array([self.rewards[i] for i in indices]),
            np.array([self.next_states[i] for i in indices]),
            np.array([self.dones[i] for i in indices]),
        )

    @property
    def size(self) -> int:
        return len(self.states)

def train_cql_policy(replay_buffer: ReplayBuffer, config: Dict) -> QNetwork:
    """
    Train a sepsis treatment policy using Conservative Q-Learning.

    CQL modifies standard Q-learning by adding a regularization term that
    penalizes high Q-values for actions that are underrepresented in the data.
    This prevents the policy from recommending actions that look good on paper
    but have no empirical support.

    The intuition: if clinicians almost never gave zero fluids to hypotensive
    patients, CQL won't optimistically assume that action would work well.
    It stays conservative, preferring well-supported actions.

    Args:
        replay_buffer: Contains all historical (state, action, reward, next_state) tuples.
        config: Training hyperparameters (CQL_CONFIG).

    Returns:
        Trained Q-network that can be used to derive the treatment policy.
    """
    # Initialize online and target Q-networks.
    q_network = QNetwork(
        state_dim=STATE_DIM,
        num_actions=NUM_ACTIONS,
        hidden_dims=config["hidden_dims"],
        lr=config["learning_rate"],
    )
    target_network = QNetwork(
        state_dim=STATE_DIM,
        num_actions=NUM_ACTIONS,
        hidden_dims=config["hidden_dims"],
        lr=config["learning_rate"],
    )
    target_network.copy_from(q_network)

    gamma = config["gamma"]
    cql_alpha = config["cql_alpha"]
    batch_size = config["batch_size"]

    print(f"Starting CQL training: {config['num_iterations']} iterations, "
          f"buffer size: {replay_buffer.size}, cql_alpha: {cql_alpha}")

    for iteration in range(config["num_iterations"]):
        # Sample a batch of transitions from the replay buffer.
        states, actions, rewards, next_states, dones = replay_buffer.sample(batch_size)

        # --- Compute standard Q-learning targets ---
        # For terminal states: target = reward (no future to discount).
        # For non-terminal: target = reward + gamma * max_a Q_target(next_state, a).
        next_q_values = target_network.forward(next_states)  # (batch, 25)
        max_next_q = np.max(next_q_values, axis=1)           # (batch,)
        targets = rewards + gamma * max_next_q * (1.0 - dones.astype(np.float32))

        # --- Compute current Q-values for the actions that were actually taken ---
        current_q_all = q_network.forward(states)  # (batch, 25)
        current_q = current_q_all[np.arange(batch_size), actions.astype(int)]  # (batch,)

        # --- CQL regularization term ---
        # Push down Q-values for all actions (logsumexp), push up for observed actions.
        # This makes the Q-function conservative: it won't overestimate actions
        # that are rare in the data.
        logsumexp_q = np.log(np.sum(np.exp(current_q_all - np.max(current_q_all, axis=1, keepdims=True)),
                                     axis=1)) + np.max(current_q_all, axis=1)
        cql_loss = cql_alpha * (logsumexp_q - current_q).mean()

        # --- Total loss: TD error + CQL penalty ---
        td_loss = np.mean((current_q - targets) ** 2)
        total_loss = td_loss + cql_loss

        # In a real implementation, you'd compute gradients and update weights here
        # using autograd (PyTorch/TensorFlow). With numpy, we'd need manual backprop.
        # For illustration, we show the loss computation and note that gradient
        # descent would minimize this loss.
        #
        # In practice, this training loop would look like:
        #   optimizer.zero_grad()
        #   loss.backward()
        #   optimizer.step()

        # Periodically update target network (soft update for stability).
        if iteration % config["target_update_freq"] == 0:
            target_network.soft_update_from(q_network, config["tau"])

        # Log progress every 5000 iterations.
        if iteration % 5000 == 0:
            print(f"  Iteration {iteration}: TD loss={td_loss:.4f}, "
                  f"CQL loss={cql_loss:.4f}, total={total_loss:.4f}")

    print("Training complete.")
    # WARNING: This returns a network with UNCHANGED random weights because numpy
    # does not support automatic differentiation. In a real PyTorch/TensorFlow
    # implementation, the gradient descent steps above would optimize the weights
    # over 50k iterations. Evaluation results below reflect random policy behavior.
    return q_network
```

---

## Step 5: Off-Policy Evaluation

*Maps to pseudocode Step 5 in the main recipe. This estimates how well the learned policy would have performed compared to what clinicians actually did. You cannot deploy without this step, and you should not trust any single OPE method in isolation.*

```python
def evaluate_policy_wis(
    q_network: QNetwork,
    test_trajectories: List[List[Dict]],
    behavior_action_probs: Dict,
) -> Dict:
    """
    Weighted Importance Sampling (WIS) for off-policy evaluation.

    The idea: reweight historical outcomes by the probability ratio of the
    learned policy vs. the behavior policy (what clinicians actually did).
    If our policy would have taken the same actions, the weight is ~1.
    If it would have done something different, we can't trust that trajectory's
    outcome as evidence for our policy.

    This method has high variance (especially when the learned policy differs
    substantially from clinician behavior), but it's unbiased under certain
    assumptions. Always report confidence intervals.

    Args:
        q_network: The trained Q-network (policy is argmax of Q-values).
        test_trajectories: Held-out patient trajectories not used in training.
        behavior_action_probs: Estimated probability of each action under the
            clinician behavior policy (from the training data distribution).

    Returns:
        Dictionary with WIS estimate, confidence interval, and agreement rate.
    """
    weighted_returns = []
    weights_list = []
    agreements = 0
    total_decisions = 0

    for trajectory in test_trajectories:
        cumulative_weight = 1.0
        trajectory_return = sum(t["reward"] for t in trajectory)

        for transition in trajectory:
            state = transition["state"]
            clinician_action = transition["action"]

            # Learned policy: argmax of Q-values with safety constraints.
            q_values = q_network.forward(state)
            safe_q = apply_safety_constraints(state, q_values)
            policy_action = int(np.argmax(safe_q))

            # Policy probability: we treat argmax as deterministic (prob=1 for best action).
            # Using 0.01 instead of 0.0 for non-selected actions avoids zero-weight
            # trajectories (which would discard all data where the policy disagrees).
            # This introduces small bias but reduces variance. In production, use a
            # softmax (Boltzmann) distribution over Q-values for proper probabilities.
            pi_prob = 1.0 if policy_action == clinician_action else 0.01

            # Behavior probability: estimated from training data action frequencies.
            # In practice, you'd condition this on the state (or state cluster).
            behavior_prob = behavior_action_probs.get(clinician_action, 1.0 / NUM_ACTIONS)

            # Importance weight: ratio of policy probability to behavior probability.
            ratio = pi_prob / max(behavior_prob, 0.001)
            cumulative_weight *= ratio

            # Clip to prevent extreme weights from dominating the estimate.
            cumulative_weight = np.clip(cumulative_weight, 0.001, 100.0)

            # Track agreement rate.
            if policy_action == clinician_action:
                agreements += 1
            total_decisions += 1

        weighted_returns.append(cumulative_weight * trajectory_return)
        weights_list.append(cumulative_weight)

    # Self-normalized WIS: divide by sum of weights for stability.
    weights_array = np.array(weights_list)
    returns_array = np.array(weighted_returns)
    wis_value = np.sum(returns_array) / np.sum(weights_array)

    # Bootstrap confidence interval (1000 resamples).
    bootstrap_estimates = []
    for _ in range(1000):
        idx = np.random.choice(len(returns_array), size=len(returns_array), replace=True)
        boot_val = np.sum(returns_array[idx]) / np.sum(weights_array[idx])
        bootstrap_estimates.append(boot_val)

    ci_lower = np.percentile(bootstrap_estimates, 2.5)
    ci_upper = np.percentile(bootstrap_estimates, 97.5)

    # Clinician baseline: average return under actual behavior.
    clinician_value = np.mean([sum(t["reward"] for t in traj) for traj in test_trajectories])

    return {
        "wis_estimated_value": float(wis_value),
        "wis_95_ci_lower": float(ci_lower),
        "wis_95_ci_upper": float(ci_upper),
        "clinician_baseline_value": float(clinician_value),
        "agreement_rate": agreements / max(total_decisions, 1),
        "num_test_trajectories": len(test_trajectories),
        "effective_sample_size": float(np.sum(weights_array) ** 2 / np.sum(weights_array ** 2)),
    }
```

---

## Step 6: Policy Serving and Recommendation

*Maps to pseudocode Step 6 in the main recipe. This is the inference path: given a patient's current state, return a treatment recommendation with safety constraints and explainability information.*

```python
def get_recommendation(
    patient_state: Dict,
    q_network: QNetwork,
    normalization_stats: Dict,
) -> Dict:
    """
    Generate a treatment recommendation for a sepsis patient.

    Takes raw clinical values, normalizes them, runs through the Q-network,
    applies safety constraints, and returns an interpretable recommendation.

    Args:
        patient_state: Dictionary of current physiological values (raw, unnormalized).
        q_network: Trained Q-network.
        normalization_stats: Dict with "mean" and "std" arrays for each feature.

    Returns:
        Recommendation dictionary with action, interpretation, confidence, and drivers.
    """
    # Construct and normalize the state vector.
    raw_state = np.array([patient_state.get(f, 0.0) for f in STATE_FEATURES], dtype=np.float32)
    means = normalization_stats["mean"]
    stds = normalization_stats["std"]
    # Avoid division by zero for features with no variance.
    normalized_state = (raw_state - means) / np.maximum(stds, 1e-8)

    # Get Q-values for all actions.
    q_values = q_network.forward(normalized_state)

    # Apply safety constraints (may mask out dangerous actions).
    # Safety constraints use raw clinical values (e.g., MAP in mmHg), not normalized features.
    safe_q_values = apply_safety_constraints(raw_state, q_values)

    # Select best action and compute confidence.
    best_action = int(np.argmax(safe_q_values))
    sorted_q = np.sort(safe_q_values[safe_q_values > -np.inf])[::-1]
    # Confidence: gap between best and second-best Q-value.
    # Larger gap = more confident the best action is clearly superior.
    confidence = float(sorted_q[0] - sorted_q[1]) if len(sorted_q) > 1 else 0.0

    # Decode action into clinical terms.
    fluid_level, vaso_level = decode_action(best_action)
    fluid_desc = _fluid_level_description(fluid_level)
    vaso_desc = _vasopressor_level_description(vaso_level)

    # Identify which safety constraints were triggered.
    original_best = int(np.argmax(q_values))
    constraints_triggered = []
    if original_best != best_action:
        constraints_triggered.append("Safety constraint overrode unconstrained recommendation")

    # Key drivers: which state features have the most extreme normalized values.
    # These are the features most likely driving the recommendation.
    feature_importance = np.abs(normalized_state)
    top_indices = np.argsort(feature_importance)[::-1][:5]
    key_drivers = [
        f"{STATE_FEATURES[i]}: {patient_state.get(STATE_FEATURES[i], 'N/A')}"
        for i in top_indices
    ]

    return {
        "recommended_action_id": best_action,
        "fluid_recommendation": fluid_desc,
        "vasopressor_recommendation": vaso_desc,
        "confidence": round(confidence, 3),
        "safety_constraints_triggered": constraints_triggered,
        "key_drivers": key_drivers,
        "top_3_actions": [
            {"action_id": int(a), "q_value": float(safe_q_values[a])}
            for a in np.argsort(safe_q_values)[::-1][:3]
            if safe_q_values[a] > -np.inf
        ],
        "disclaimer": "Advisory only. Clinical judgment supersedes all recommendations.",
    }

def _fluid_level_description(level: int) -> str:
    """Human-readable description of a fluid level."""
    descriptions = [
        "No additional IV fluids this window",
        "Minimal maintenance fluids (~250 mL)",
        "Moderate fluid resuscitation (~500 mL)",
        "Aggressive fluid resuscitation (~1000 mL)",
        "Very aggressive fluid bolus (~2000+ mL)",
    ]
    return descriptions[min(level, len(descriptions) - 1)]

def _vasopressor_level_description(level: int) -> str:
    """Human-readable description of a vasopressor level."""
    descriptions = [
        "No vasopressor support",
        "Low-dose vasopressor (NE ~0.08 mcg/kg/min)",
        "Moderate vasopressor support (NE ~0.16 mcg/kg/min)",
        "High-dose vasopressor support (NE ~0.28 mcg/kg/min)",
        "Maximal vasopressor support (NE ~0.45+ mcg/kg/min)",
    ]
    return descriptions[min(level, len(descriptions) - 1)]
```

---

## Step 7: AWS Integration (SageMaker + S3 + DynamoDB)

*This section shows how the pieces connect to AWS services for training, storage, and serving.*

```python
def upload_trajectories_to_s3(trajectories: List[List[Dict]], experiment_id: str):
    """
    Upload processed trajectories to S3 for SageMaker training jobs.

    Trajectories are serialized as numpy arrays (states, actions, rewards, etc.)
    and stored in a format that SageMaker training containers can read.
    """
    s3_client = boto3.client("s3", config=BOTO3_CONFIG)

    # Flatten all trajectories into arrays for efficient storage.
    all_states = []
    all_actions = []
    all_rewards = []
    all_next_states = []
    all_dones = []

    for trajectory in trajectories:
        for t in trajectory:
            all_states.append(t["state"])
            all_actions.append(t["action"])
            all_rewards.append(t["reward"])
            all_next_states.append(t["next_state"])
            all_dones.append(t["done"])

    # Save as .npz (compressed numpy archive).
    import io
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        states=np.array(all_states),
        actions=np.array(all_actions),
        rewards=np.array(all_rewards),
        next_states=np.array(all_next_states),
        dones=np.array(all_dones),
    )
    buffer.seek(0)

    key = f"{TRAJECTORY_PREFIX}{experiment_id}/trajectories.npz"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buffer.getvalue(),
        ServerSideEncryption="aws:kms",  # PHI requires KMS encryption
    )
    print(f"Uploaded {len(all_states)} transitions to s3://{S3_BUCKET}/{key}")
    return f"s3://{S3_BUCKET}/{key}"

def log_recommendation_to_dynamodb(patient_id: str, recommendation: Dict):
    """
    Log every recommendation to DynamoDB for audit trail and outcome tracking.

    Every recommendation the system generates must be logged, regardless of
    whether the clinician follows it. This enables:
    - Regulatory audit (who saw what recommendation, when)
    - Outcome tracking (did following/ignoring recommendations correlate with outcomes?)
    - Model monitoring (is the recommendation distribution shifting over time?)
    """
    dynamodb = boto3.resource("dynamodb", config=BOTO3_CONFIG)
    table = dynamodb.Table(AUDIT_TABLE)

    # DynamoDB requires Decimal for numeric types (not float).
    item = {
        "recommendation_id": str(uuid.uuid4()),
        "patient_id": patient_id,
        "timestamp": int(time.time()),
        "recommended_action": recommendation["recommended_action_id"],
        "fluid_recommendation": recommendation["fluid_recommendation"],
        "vasopressor_recommendation": recommendation["vasopressor_recommendation"],
        "confidence": Decimal(str(round(recommendation["confidence"], 4))),
        "safety_constraints_triggered": recommendation["safety_constraints_triggered"],
        "key_drivers": recommendation["key_drivers"],
    }

    table.put_item(Item=item)
    # PHI Safety: Never log the raw patient state values to the audit table.
    # Log only the recommendation and metadata.

def publish_evaluation_metrics(eval_results: Dict, experiment_id: str):
    """
    Publish off-policy evaluation metrics to CloudWatch for monitoring.

    These metrics let you track policy quality over time as you retrain
    with new data. Alert on significant drops in estimated value or
    agreement rate.
    """
    cloudwatch = boto3.client("cloudwatch", config=BOTO3_CONFIG)

    metrics = [
        {
            "MetricName": "WISEstimatedValue",
            "Value": eval_results["wis_estimated_value"],
            "Unit": "None",
            "Dimensions": [{"Name": "ExperimentId", "Value": experiment_id}],
        },
        {
            "MetricName": "ClinicianAgreementRate",
            "Value": eval_results["agreement_rate"],
            "Unit": "None",
            "Dimensions": [{"Name": "ExperimentId", "Value": experiment_id}],
        },
        {
            "MetricName": "EffectiveSampleSize",
            "Value": eval_results["effective_sample_size"],
            "Unit": "Count",
            "Dimensions": [{"Name": "ExperimentId", "Value": experiment_id}],
        },
    ]

    cloudwatch.put_metric_data(
        Namespace="SepsisRL/PolicyEvaluation",
        MetricData=metrics,
    )
    print(f"Published {len(metrics)} evaluation metrics to CloudWatch")
```

---

## Full Pipeline

This assembles all the steps into a single callable flow. In practice, you'd run cohort extraction and training as a batch job (SageMaker Training Job or Step Functions workflow), and inference as a real-time endpoint.

```python
def run_training_pipeline(patient_data_list: List[Dict], experiment_id: str) -> Dict:
    """
    End-to-end training pipeline: build trajectories, train CQL policy, evaluate.

    Args:
        patient_data_list: List of patient data dicts (each with "time_steps" and "survived").
        experiment_id: Unique identifier for this training run.

    Returns:
        Dictionary with trained model, evaluation results, and metadata.
    """
    print(f"=== Sepsis RL Training Pipeline: {experiment_id} ===")
    print(f"Patients: {len(patient_data_list)}")

    # Step 1: Build trajectories from raw patient data.
    print("\n[1/4] Building trajectories...")
    replay_buffer = ReplayBuffer()
    all_trajectories = []
    for patient_data in patient_data_list:
        trajectory = build_trajectory(patient_data)
        if len(trajectory) > 0:
            replay_buffer.add_trajectory(trajectory)
            all_trajectories.append(trajectory)

    print(f"  Built {len(all_trajectories)} trajectories, "
          f"{replay_buffer.size} total transitions")

    # Step 2: Upload to S3 for reproducibility.
    print("\n[2/4] Uploading trajectories to S3...")
    upload_trajectories_to_s3(all_trajectories, experiment_id)

    # Step 3: Train CQL policy.
    print("\n[3/4] Training CQL policy...")
    q_network = train_cql_policy(replay_buffer, CQL_CONFIG)

    # Step 4: Evaluate on held-out data (last 20% of trajectories).
    print("\n[4/4] Running off-policy evaluation...")
    split_idx = int(len(all_trajectories) * 0.8)
    test_trajectories = all_trajectories[split_idx:]

    # Estimate behavior policy action probabilities from training data.
    train_actions = [t["action"] for traj in all_trajectories[:split_idx] for t in traj]
    action_counts = np.bincount(train_actions, minlength=NUM_ACTIONS)
    behavior_probs = {a: count / len(train_actions) for a, count in enumerate(action_counts)}

    eval_results = evaluate_policy_wis(q_network, test_trajectories, behavior_probs)

    print(f"\n=== Evaluation Results ===")
    print(f"  WIS estimated value: {eval_results['wis_estimated_value']:.3f}")
    print(f"  95% CI: [{eval_results['wis_95_ci_lower']:.3f}, {eval_results['wis_95_ci_upper']:.3f}]")
    print(f"  Clinician baseline: {eval_results['clinician_baseline_value']:.3f}")
    print(f"  Agreement rate: {eval_results['agreement_rate']:.1%}")
    print(f"  Effective sample size: {eval_results['effective_sample_size']:.0f}")

    # Publish metrics to CloudWatch.
    publish_evaluation_metrics(eval_results, experiment_id)

    return {
        "q_network": q_network,
        "eval_results": eval_results,
        "experiment_id": experiment_id,
        "num_patients": len(all_trajectories),
        "num_transitions": replay_buffer.size,
    }

def run_inference_example():
    """
    Demonstrate the inference path: given a patient state, get a recommendation.

    In production, this would be a SageMaker endpoint receiving requests from
    the clinical decision support system.
    """
    print("\n=== Inference Example ===")

    # Example patient state (a moderately sick sepsis patient, 12 hours in).
    patient_state = {
        "heart_rate": 112,
        "mean_arterial_pressure": 62,
        "temperature": 38.9,
        "respiratory_rate": 24,
        "spo2": 94,
        "lactate": 4.2,
        "creatinine": 1.8,
        "bilirubin": 1.2,
        "platelet_count": 145,
        "wbc": 18.5,
        "ph": 7.31,
        "pao2_fio2_ratio": 220,
        "urine_output_4h": 80,
        "cumulative_fluid_balance": 3200,
        "gcs_score": 14,
        "sofa_score": 8,
        "hours_since_admission": 12,
        "age": 67,
    }

    # In production, you'd load the trained model from S3/SageMaker.
    # Here we create a dummy network for demonstration.
    dummy_network = QNetwork(
        state_dim=STATE_DIM,
        num_actions=NUM_ACTIONS,
        hidden_dims=CQL_CONFIG["hidden_dims"],
        lr=CQL_CONFIG["learning_rate"],
    )

    # Normalization stats would come from the training data.
    # Using placeholder values here.
    normalization_stats = {
        "mean": np.zeros(STATE_DIM),
        "std": np.ones(STATE_DIM),
    }

    recommendation = get_recommendation(patient_state, dummy_network, normalization_stats)

    print(f"  Patient: MAP={patient_state['mean_arterial_pressure']}, "
          f"Lactate={patient_state['lactate']}, SOFA={patient_state['sofa_score']}")
    print(f"  Recommendation: {recommendation['fluid_recommendation']}")
    print(f"  Vasopressor: {recommendation['vasopressor_recommendation']}")
    print(f"  Confidence: {recommendation['confidence']}")
    print(f"  Key drivers: {recommendation['key_drivers'][:3]}")
    if recommendation["safety_constraints_triggered"]:
        print(f"  Safety constraints: {recommendation['safety_constraints_triggered']}")
    print(f"  Disclaimer: {recommendation['disclaimer']}")

    # Log to audit trail.
    # log_recommendation_to_dynamodb("ANON-ICU-4821", recommendation)

# Entry point
if __name__ == "__main__":
    # For demonstration, generate synthetic patient data.
    # In reality, this comes from your EHR data pipeline (AWS Glue job).
    print("Generating synthetic sepsis trajectories for demonstration...")
    synthetic_patients = []
    for i in range(100):  # 100 synthetic patients (real: 10,000+)
        num_steps = np.random.randint(5, 20)  # 5-20 time steps (20-80 hours)
        survived = np.random.random() > 0.25  # 75% survival rate (simplified)
        time_steps = []
        for t in range(num_steps):
            time_steps.append({
                "heart_rate": np.random.normal(100, 20),
                "mean_arterial_pressure": np.random.normal(65, 12),
                "temperature": np.random.normal(38.5, 1.0),
                "respiratory_rate": np.random.normal(22, 5),
                "spo2": np.random.normal(95, 3),
                "lactate": max(0.5, np.random.normal(3.0, 2.0)),
                "creatinine": max(0.3, np.random.normal(1.5, 0.8)),
                "bilirubin": max(0.1, np.random.normal(1.0, 0.5)),
                "platelet_count": max(20, np.random.normal(180, 80)),
                "wbc": max(1, np.random.normal(14, 6)),
                "ph": np.random.normal(7.35, 0.08),
                "pao2_fio2_ratio": max(50, np.random.normal(250, 80)),
                "urine_output_4h": max(0, np.random.normal(150, 80)),
                "cumulative_fluid_balance": np.random.normal(2000, 1500),
                "gcs_score": min(15, max(3, int(np.random.normal(13, 3)))),
                "sofa_score": max(0, int(np.random.normal(7, 3))),
                "hours_since_admission": t * 4,
                "age": np.random.normal(65, 12),
                "iv_fluid_ml": max(0, np.random.normal(500, 400)),
                "vasopressor_dose": max(0, np.random.normal(0.1, 0.12)),
            })
        synthetic_patients.append({
            "patient_id": f"SYNTH-{i:04d}",
            "time_steps": time_steps,
            "survived": survived,
        })

    # Run the training pipeline.
    results = run_training_pipeline(synthetic_patients, experiment_id="demo-2026-001")

    # Run inference example.
    run_inference_example()
```

---

## Gap to Production

The code above demonstrates the mechanics of offline RL for sepsis treatment. Here's what separates it from something you'd actually deploy:

**Data pipeline robustness.** Real EHR data is messy. Missing values, inconsistent timestamps, medication name variations, unit conversions (mg vs. mcg, mL vs. L), and charting errors. You need a battle-tested ETL pipeline (AWS Glue) with extensive validation checks, not the clean synthetic data shown here. Budget 60-70% of your engineering time for data quality.

**Proper deep learning framework.** The numpy Q-network above is for illustration. A real implementation uses PyTorch or TensorFlow with GPU acceleration (SageMaker ml.p3 or ml.g4dn instances). You'd also want proper gradient computation, batch normalization, dropout for regularization, and learning rate scheduling.

**Multiple OPE methods.** Never trust a single off-policy evaluation method. Use WIS, Fitted Q-Evaluation (FQE), and doubly robust estimators. Report all of them with confidence intervals. If they disagree substantially, that's a red flag.

**Hyperparameter sensitivity analysis.** The CQL alpha, discount factor, reward weights, and action discretization bins all affect the learned policy. You need systematic sweeps (SageMaker Hyperparameter Tuning) to understand how sensitive the policy is to these choices. A policy that changes dramatically with small hyperparameter changes is not trustworthy.

**Clinician review interface.** Before any deployment, domain experts need to review the learned policy. Show them: "For patients in state X, the policy recommends action Y. Does this make clinical sense?" Build a review tool that samples representative states and shows the policy's recommendations alongside what clinicians actually did.

**Prospective shadow mode.** Run the system in parallel with clinical care (generating recommendations but not showing them) for months. Compare its recommendations against actual decisions and outcomes. This is the minimum validation before any clinician-facing deployment.

**Model versioning and drift detection.** Track which model version generated each recommendation. Monitor for distribution shift: are you seeing patient states that are far from the training distribution? CloudWatch alarms on out-of-distribution detection metrics.

**Error handling and retries.** The code above has no error handling. Production needs: exponential backoff on API calls, graceful degradation if the model endpoint is unavailable, input validation (reject states with physiologically impossible values), and structured logging (never log PHI values, only metadata).

**IAM least privilege.** The training job needs different permissions than the inference endpoint. The inference endpoint should only be able to read the model artifact and write to the audit table. It should not have access to raw patient data or the ability to modify the model.

**VPC isolation.** SageMaker training jobs and endpoints processing PHI must run in a VPC with no internet access. Use VPC endpoints for S3, DynamoDB, CloudWatch, and SageMaker API calls. This prevents accidental data exfiltration.

**Regulatory pathway.** If this system provides specific treatment recommendations (which it does), it likely requires FDA clearance as a Clinical Decision Support tool. The regulatory submission requires extensive documentation of the algorithm, training data, validation methodology, and intended use. This is a multi-year process that starts long before the code is written.

---

*← [Recipe 15.4: Sepsis Treatment Optimization](chapter15.04-sepsis-treatment-optimization) · [Chapter 15 Index](chapter15-preface) · [Next: Recipe 15.5 →](chapter15.05-ventilator-weaning-protocols)*
