# Recipe 15.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the concepts from Recipe 15.9. It demonstrates the shape of a radiation therapy adaptive planning system using offline reinforcement learning. It is absolutely not production-ready, not clinically validated, and not something you would deploy anywhere near a treatment machine. The physics is simplified. The tumor dynamics are a toy model. The dose calculations are approximations of approximations. Think of it as a learning tool: code you can run to understand how the RL pieces fit together for sequential treatment adaptation. A starting point for research, not a destination for clinical use.

---

## Setup

You'll need these packages:

```bash
pip install boto3 numpy
```

For the RL training components:

```bash
pip install torch
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role needs: `sagemaker:CreateTrainingJob`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `lambda:InvokeFunction`.

This example runs locally for demonstration. In practice, the training step runs on SageMaker with GPU instances, and the inference step runs as a Lambda function invoked before each treatment fraction.

---

## Config and Constants

Before we get to the logic, here's the configuration that drives the system. These constants encode radiation physics constraints, clinical tolerances, and reward function weights. The organ-at-risk (OAR) dose tolerances come from published clinical guidelines (QUANTEC, for example). The reward weights are value judgments made by radiation oncologists about how to balance tumor control against normal tissue sparing. Different institutions, different tumor sites, different patient populations might set these differently.

```python
import logging
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Tuple, Optional

import numpy as np
import boto3
from botocore.config import Config

# --- Logging ---
# Never log PHI (patient identifiers, imaging data, treatment details).
# Log operational metrics only: counts, latencies, error types.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- AWS Configuration ---
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
AWS_REGION = "us-east-1"

# --- Treatment Parameters ---
# Head and neck cancer: typical fractionation is 70 Gy in 35 fractions (2 Gy/fraction).
TOTAL_FRACTIONS = 35
PRESCRIBED_DOSE_PER_FRACTION_GY = 2.0
TOTAL_PRESCRIBED_DOSE_GY = TOTAL_FRACTIONS * PRESCRIBED_DOSE_PER_FRACTION_GY  # 70 Gy

# --- Organ-at-Risk Dose Tolerances (Gy) ---
# These are hard constraints. Exceeding them causes serious complications.
# Values from QUANTEC guidelines (simplified for this example).
OAR_TOLERANCES = {
    "spinal_cord": 45.0,        # Myelopathy risk above this
    "brainstem": 54.0,          # Necrosis risk
    "parotid_left": 26.0,      # Mean dose; xerostomia (dry mouth) above this
    "parotid_right": 26.0,     # Same for contralateral
    "optic_nerve": 54.0,       # Vision loss risk
    "cochlea_left": 45.0,      # Hearing loss
    "cochlea_right": 45.0,
    "mandible": 70.0,          # Osteoradionecrosis
}

# Safety margin: trigger warnings at this fraction of tolerance.
SAFETY_MARGIN_FRACTION = 0.85

# --- State Space ---
# 18 features representing what the system observes at each fraction.
STATE_DIM = 18

# --- Action Space ---
# Discrete actions the agent can recommend at each fraction.
ACTIONS = ["continue", "adjust_intensity", "replan"]
NUM_ACTIONS = len(ACTIONS)

# --- Reward Function Weights ---
# These encode the clinical tradeoff between tumor control and tissue sparing.
# TCP = tumor control probability. NTCP = normal tissue complication probability.
TCP_WEIGHT = 10.0               # Reward for maintaining good tumor coverage
NTCP_PENALTY_WEIGHT = 8.0      # Penalty for OAR dose approaching tolerance
REPLAN_COST = 2.0              # Cost of replanning (clinical resources, patient time)
COVERAGE_LOSS_PENALTY = 15.0   # Penalty for tumor underdosing
CONSTRAINT_VIOLATION_PENALTY = 100.0  # Hard penalty for exceeding OAR tolerance

# --- Training Hyperparameters ---
GAMMA = 0.99            # Discount factor (future fractions matter almost as much)
CQL_ALPHA = 2.0         # CQL conservatism (higher than chemo because stakes are higher)
LEARNING_RATE = 1e-4
BATCH_SIZE = 64
NUM_EPOCHS = 100

# --- DynamoDB Table Names ---
STATE_TABLE = "radiation-adaptive-patient-states"
RECOMMENDATION_TABLE = "radiation-adaptive-recommendations"
```

---

## Step 1: Define the State Representation

*The main recipe describes a high-dimensional state vector capturing tumor geometry, cumulative dosimetry, and treatment trajectory. This step builds that vector from the data available at each fraction.*

```python
def build_state_vector(
    fraction_number: int,
    tumor_volume_ratio: float,
    tumor_volume_change_rate: float,
    cumulative_ptv_dose_gy: float,
    cumulative_oar_doses: Dict[str, float],
    plan_conformity_index: float,
    plan_homogeneity_index: float,
    patient_weight_change_kg: float,
    fractions_since_replan: int,
    current_plan_age_fractions: int,
) -> np.ndarray:
    """
    Construct a normalized state vector from clinical and dosimetric data.

    Each feature is scaled to roughly [0, 1] so the neural network sees
    consistent magnitudes. The normalization constants come from typical
    clinical ranges for head and neck radiation therapy.

    Args:
        fraction_number: Current fraction (1 to 35).
        tumor_volume_ratio: Current tumor volume / baseline volume (0.3 to 1.2 typical).
        tumor_volume_change_rate: Rate of volume change over last 5 fractions.
        cumulative_ptv_dose_gy: Total dose delivered to planning target volume so far.
        cumulative_oar_doses: Dict mapping OAR name to cumulative mean dose in Gy.
        plan_conformity_index: How well dose conforms to target (1.0 = perfect).
        plan_homogeneity_index: Dose uniformity within target (lower = more uniform).
        patient_weight_change_kg: Weight change from baseline (negative = loss).
        fractions_since_replan: How many fractions since the last plan change.
        current_plan_age_fractions: Total age of current plan in fractions.

    Returns:
        Numpy array of shape (STATE_DIM,) with normalized features.
    """
    # Normalize cumulative OAR doses by their respective tolerances.
    # This gives us a "fraction of tolerance used" for each OAR (0 to 1+).
    spinal_cord_frac = cumulative_oar_doses.get("spinal_cord", 0) / OAR_TOLERANCES["spinal_cord"]
    parotid_l_frac = cumulative_oar_doses.get("parotid_left", 0) / OAR_TOLERANCES["parotid_left"]
    parotid_r_frac = cumulative_oar_doses.get("parotid_right", 0) / OAR_TOLERANCES["parotid_right"]
    brainstem_frac = cumulative_oar_doses.get("brainstem", 0) / OAR_TOLERANCES["brainstem"]
    optic_frac = cumulative_oar_doses.get("optic_nerve", 0) / OAR_TOLERANCES["optic_nerve"]

    # Fraction progress through treatment (0 at start, 1 at end).
    fraction_progress = fraction_number / TOTAL_FRACTIONS

    # How much of the prescribed dose has been delivered.
    dose_progress = cumulative_ptv_dose_gy / TOTAL_PRESCRIBED_DOSE_GY

    state = np.array([
        fraction_progress,                          # 0: where we are in treatment
        1.0 - fraction_progress,                    # 1: fractions remaining (normalized)
        tumor_volume_ratio,                         # 2: tumor shrinkage (1.0 = no change)
        np.clip(tumor_volume_change_rate + 0.5, 0, 1),  # 3: rate of change (centered)
        dose_progress,                              # 4: dose delivered vs planned
        spinal_cord_frac,                           # 5: spinal cord dose fraction
        parotid_l_frac,                             # 6: left parotid dose fraction
        parotid_r_frac,                             # 7: right parotid dose fraction
        brainstem_frac,                             # 8: brainstem dose fraction
        optic_frac,                                 # 9: optic nerve dose fraction
        np.clip(plan_conformity_index / 2.0, 0, 1),  # 10: conformity (1.0 ideal, >1 worse)
        np.clip(plan_homogeneity_index / 0.3, 0, 1), # 11: homogeneity (0 ideal, >0 worse)
        np.clip((patient_weight_change_kg + 10) / 20, 0, 1),  # 12: weight change
        fractions_since_replan / TOTAL_FRACTIONS,   # 13: time since last replan
        current_plan_age_fractions / TOTAL_FRACTIONS,  # 14: plan age
        # Derived safety features: how close are we to any OAR limit?
        max(spinal_cord_frac, parotid_l_frac, parotid_r_frac, brainstem_frac, optic_frac),  # 15: worst OAR
        # Is dose delivery on track? (should be ~equal to fraction_progress)
        np.clip(dose_progress - fraction_progress + 0.5, 0, 1),  # 16: dose tracking
        # Tumor response relative to expected (faster shrinkage = good)
        np.clip(1.0 - tumor_volume_ratio, 0, 1),   # 17: response magnitude
    ], dtype=np.float32)

    return state
```

---

## Step 2: Compute the Reward

*The reward function balances tumor control probability against normal tissue complication probability, with a cost for replanning. This is where clinical judgment becomes math. The weights are not learned; they're decisions made by radiation oncologists.*

```python
def compute_reward(
    current_state: np.ndarray,
    action: str,
    next_state: np.ndarray,
) -> float:
    """
    Compute the reward for a single fraction transition.

    The reward captures three things:
    1. Tumor coverage: is the target getting adequate dose?
    2. OAR sparing: are organs at risk staying below tolerance?
    3. Replanning cost: each replan consumes clinical resources.

    Hard constraint violations (OAR exceeding tolerance) get a massive
    penalty that dominates everything else. This ensures the policy
    learns to avoid them absolutely, not just on average.

    Args:
        current_state: State vector at decision time.
        action: The action taken ("continue", "adjust_intensity", "replan").
        next_state: State vector at the next fraction.

    Returns:
        Scalar reward value.
    """
    reward = 0.0

    # --- Tumor coverage component ---
    # Check if dose delivery is on track (state index 16: dose tracking).
    # Values near 0.5 mean on track. Below 0.5 means underdosing.
    dose_tracking = next_state[16]
    if dose_tracking < 0.45:
        # Underdosing the tumor. This is bad for tumor control.
        reward -= COVERAGE_LOSS_PENALTY * (0.45 - dose_tracking)
    elif dose_tracking >= 0.48 and dose_tracking <= 0.55:
        # On track. Small positive reward for maintaining coverage.
        reward += TCP_WEIGHT * 0.1

    # --- Tumor response component ---
    # Reward tumor shrinkage (state index 17: response magnitude).
    response = next_state[17]
    reward += TCP_WEIGHT * response * 0.05  # Small continuous reward for response

    # --- OAR sparing component ---
    # Penalize as OAR doses approach tolerance (state indices 5-9).
    oar_fractions = next_state[5:10]
    for oar_frac in oar_fractions:
        if oar_frac > 1.0:
            # HARD CONSTRAINT VIOLATION. This must never happen.
            reward -= CONSTRAINT_VIOLATION_PENALTY
        elif oar_frac > SAFETY_MARGIN_FRACTION:
            # Approaching tolerance. Increasing penalty as we get closer.
            overshoot = oar_frac - SAFETY_MARGIN_FRACTION
            reward -= NTCP_PENALTY_WEIGHT * overshoot * 5.0

    # --- Replanning cost ---
    if action == "replan":
        reward -= REPLAN_COST
    elif action == "adjust_intensity":
        reward -= REPLAN_COST * 0.3  # Minor adjustments are cheaper

    # --- Plan quality degradation ---
    # If conformity or homogeneity are worsening, penalize "continue."
    conformity_change = next_state[10] - current_state[10]
    if action == "continue" and conformity_change > 0.05:
        # Plan quality is degrading and we're not doing anything about it.
        reward -= 1.0

    return reward
```

---

## Step 3: Safety Constraint Enforcement

*This is the most critical piece. In radiation therapy, constraint violations are not "suboptimal outcomes" that you can tolerate occasionally. They cause permanent damage. The safety layer overrides the policy whenever a recommended action would risk exceeding OAR tolerances.*

```python
def check_safety_constraints(
    state: np.ndarray,
    recommended_action: str,
) -> Tuple[str, List[str]]:
    """
    Verify that the recommended action doesn't risk OAR tolerance violations.

    This function implements hard safety constraints that override the policy.
    Even if the RL agent is 99% confident in "continue," if continuing would
    push the spinal cord past 45 Gy, we override to "replan."

    The logic:
    - If any OAR is above the safety margin AND the plan is old, force replan.
    - If any OAR is above tolerance, force replan (emergency).
    - Otherwise, allow the policy's recommendation.

    Args:
        state: Current normalized state vector.
        recommended_action: What the policy wants to do.

    Returns:
        Tuple of (safe_action, list_of_violations).
        If no violations, returns the original action with empty list.
    """
    violations = []

    # Extract OAR dose fractions (indices 5-9).
    oar_names = ["spinal_cord", "parotid_left", "parotid_right", "brainstem", "optic_nerve"]
    oar_fractions = state[5:10]

    # Check for hard constraint violations (already exceeded tolerance).
    for name, frac in zip(oar_names, oar_fractions):
        if frac >= 1.0:
            violations.append(f"CRITICAL: {name} at {frac*100:.1f}% of tolerance (exceeded)")

    # If any OAR has already exceeded tolerance, force immediate replan.
    if any(f >= 1.0 for f in oar_fractions):
        return "replan", violations

    # Check for approaching tolerance with "continue" action.
    if recommended_action == "continue":
        fractions_remaining_ratio = state[1]  # index 1: fractions remaining normalized
        for name, frac in zip(oar_names, oar_fractions):
            if frac > SAFETY_MARGIN_FRACTION:
                # OAR is above 85% of tolerance. If we have many fractions left,
                # continuing the current plan will likely exceed tolerance.
                if fractions_remaining_ratio > 0.3:
                    violations.append(
                        f"WARNING: {name} at {frac*100:.1f}% of tolerance "
                        f"with {fractions_remaining_ratio*100:.0f}% of treatment remaining"
                    )

        # If we have warnings and the plan is old, override to replan.
        plan_age = state[14]  # index 14: plan age normalized
        if violations and plan_age > 0.3:
            return "replan", violations

        # If warnings but plan is recent, suggest adjustment instead.
        if violations:
            return "adjust_intensity", violations

    return recommended_action, violations
```

---

## Step 4: The Q-Network (Conservative Q-Learning)

*The policy is a neural network that maps states to Q-values for each action. We train it with Conservative Q-Learning (CQL), which penalizes Q-values for actions that weren't well-represented in the training data. This prevents the policy from being overconfident about actions it hasn't seen evidence for.*

```python
import torch
import torch.nn as nn
import torch.optim as optim


class AdaptivePlanningQNetwork(nn.Module):
    """
    Q-network for radiation therapy adaptive planning.

    Maps a state vector (18 features) to Q-values for 3 actions
    (continue, adjust_intensity, replan).

    Architecture is simple: two hidden layers with ReLU activation.
    For a 3-action discrete problem with 18 state features, this is
    more than sufficient. Deeper networks don't help here because the
    state representation already encodes the relevant features.
    """

    def __init__(self, state_dim: int = STATE_DIM, action_dim: int = NUM_ACTIONS):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass: state -> Q-values for all actions."""
        return self.network(state)

    def get_action(self, state: np.ndarray) -> int:
        """Select the action with highest Q-value (greedy policy)."""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.forward(state_tensor).squeeze(0)
            return int(q_values.argmax().item())

    def get_action_confidence(self, state: np.ndarray, action_index: int) -> float:
        """
        Compute confidence as softmax probability of the chosen action.

        Higher confidence means the Q-value for this action is much larger
        than alternatives. Low confidence means the agent is uncertain
        (multiple actions have similar Q-values).
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.forward(state_tensor).squeeze(0)
            probs = torch.softmax(q_values * 2.0, dim=0)  # temperature=0.5
            return float(probs[action_index].item())
```

---

## Step 5: CQL Training Loop

*Conservative Q-Learning adds a penalty term to the standard Bellman loss. It pushes down Q-values for actions not in the dataset and pushes up Q-values for actions that were actually taken. This makes the policy conservative: it won't recommend actions that differ wildly from historical clinical practice.*

```python
def train_cql_policy(
    trajectories: List[List[Dict]],
    num_epochs: int = NUM_EPOCHS,
    batch_size: int = BATCH_SIZE,
) -> AdaptivePlanningQNetwork:
    """
    Train a CQL policy from offline treatment trajectories.

    Each trajectory is one patient's full treatment course (up to 35 fractions).
    Each transition contains: state, action_index, reward, next_state, done.

    CQL loss = standard Bellman loss + alpha * (logsumexp(Q) - Q(data_action))

    The second term penalizes high Q-values for actions not in the data,
    preventing overestimation of untested actions.

    Args:
        trajectories: List of patient trajectories (list of transition dicts).
        num_epochs: Training epochs.
        batch_size: Mini-batch size.

    Returns:
        Trained Q-network.
    """
    # Flatten trajectories into a replay buffer.
    buffer_states = []
    buffer_actions = []
    buffer_rewards = []
    buffer_next_states = []
    buffer_dones = []

    for trajectory in trajectories:
        for transition in trajectory:
            buffer_states.append(transition["state"])
            buffer_actions.append(transition["action_index"])
            buffer_rewards.append(transition["reward"])
            buffer_next_states.append(transition["next_state"])
            buffer_dones.append(transition["done"])

    buffer_states = np.array(buffer_states)
    buffer_actions = np.array(buffer_actions)
    buffer_rewards = np.array(buffer_rewards, dtype=np.float32)
    buffer_next_states = np.array(buffer_next_states)
    buffer_dones = np.array(buffer_dones, dtype=np.float32)

    num_samples = len(buffer_states)
    logger.info("Training CQL on %d transitions from %d trajectories", num_samples, len(trajectories))

    # Initialize networks.
    policy = AdaptivePlanningQNetwork()
    target_network = AdaptivePlanningQNetwork()
    target_network.load_state_dict(policy.state_dict())

    optimizer = optim.Adam(policy.parameters(), lr=LEARNING_RATE)

    for epoch in range(num_epochs):
        epoch_loss = 0.0
        num_batches = 0

        # Shuffle and iterate in mini-batches.
        indices = np.random.permutation(num_samples)

        for start in range(0, num_samples - batch_size, batch_size):
            batch_idx = indices[start:start + batch_size]

            states = torch.FloatTensor(buffer_states[batch_idx])
            actions = torch.LongTensor(buffer_actions[batch_idx])
            rewards = torch.FloatTensor(buffer_rewards[batch_idx])
            next_states = torch.FloatTensor(buffer_next_states[batch_idx])
            dones = torch.FloatTensor(buffer_dones[batch_idx])

            # Current Q-values for the actions that were actually taken.
            current_q = policy(states).gather(1, actions.unsqueeze(1)).squeeze(1)

            # Target Q-values (Bellman target).
            with torch.no_grad():
                next_q = target_network(next_states).max(dim=1)[0]
                target_q = rewards + GAMMA * next_q * (1.0 - dones)

            # Standard Bellman loss.
            bellman_loss = nn.functional.mse_loss(current_q, target_q)

            # CQL regularization term.
            # Push down Q-values for all actions (logsumexp), push up for data actions.
            all_q = policy(states)
            cql_penalty = (
                torch.logsumexp(all_q, dim=1).mean()
                - all_q.gather(1, actions.unsqueeze(1)).squeeze(1).mean()
            )

            # Combined loss.
            loss = bellman_loss + CQL_ALPHA * cql_penalty

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            num_batches += 1

        # Update target network periodically (soft update).
        if (epoch + 1) % 5 == 0:
            for param, target_param in zip(policy.parameters(), target_network.parameters()):
                target_param.data.copy_(0.95 * target_param.data + 0.05 * param.data)

        if (epoch + 1) % 20 == 0:
            avg_loss = epoch_loss / max(num_batches, 1)
            logger.info("  Epoch %d/%d, avg loss: %.4f", epoch + 1, num_epochs, avg_loss)

    return policy
```

---

## Step 6: Generate Explanation for Clinician

*A recommendation without explanation is useless in radiation oncology. The physicist and oncologist need to understand why the system recommends replanning now rather than next week. This step identifies the key factors driving the recommendation.*

```python
def generate_explanation(
    state: np.ndarray,
    policy: AdaptivePlanningQNetwork,
    action_index: int,
) -> Dict:
    """
    Generate a human-readable explanation of the recommendation.

    The main recipe's pseudocode uses SHAP values for feature attribution.
    Here we use a simpler perturbation approach (no extra dependency).
    For production, SHAP gives more accurate attributions when features
    are correlated (e.g., dose_progress and fraction_progress).

    Uses perturbation-based feature importance: for each state feature,
    slightly change it and measure how much the Q-value changes. Features
    that cause large Q-value changes are the ones driving the decision.

    Args:
        state: Current normalized state vector.
        policy: Trained Q-network.
        action_index: The recommended action index.

    Returns:
        Dictionary with primary factors and expected benefit.
    """
    feature_names = [
        "fraction_progress", "fractions_remaining", "tumor_volume_ratio",
        "tumor_change_rate", "dose_progress", "spinal_cord_dose",
        "parotid_left_dose", "parotid_right_dose", "brainstem_dose",
        "optic_nerve_dose", "plan_conformity", "plan_homogeneity",
        "weight_change", "fractions_since_replan", "plan_age",
        "worst_oar_fraction", "dose_tracking", "tumor_response",
    ]

    # Get baseline Q-value.
    with torch.no_grad():
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        baseline_q = policy(state_tensor).squeeze(0)[action_index].item()

    # Perturb each feature and measure Q-value change.
    # Limitation: one-directional perturbation (+0.1 only). For production,
    # perturb both directions and average the absolute Q-value changes, or use SHAP.
    importances = []
    for i, name in enumerate(feature_names):
        perturbed = state.copy()
        perturbed[i] = min(perturbed[i] + 0.1, 1.0)
        with torch.no_grad():
            perturbed_tensor = torch.FloatTensor(perturbed).unsqueeze(0)
            perturbed_q = policy(perturbed_tensor).squeeze(0)[action_index].item()
        importance = abs(perturbed_q - baseline_q)
        importances.append({"feature": name, "importance": round(importance, 4)})

    importances.sort(key=lambda x: x["importance"], reverse=True)

    # Translate top factors into clinical language.
    top_factors = []
    for factor in importances[:3]:
        feature_idx = feature_names.index(factor["feature"])
        value = state[feature_idx]
        top_factors.append(
            _translate_factor(factor["feature"], value, factor["importance"])
        )

    # Compute expected benefit of recommended action vs. "continue."
    with torch.no_grad():
        q_values = policy(state_tensor).squeeze(0)
        continue_q = q_values[0].item()  # action 0 = continue
        recommended_q = q_values[action_index].item()
        expected_benefit = recommended_q - continue_q

    return {
        "primary_factors": top_factors,
        "expected_benefit_over_continue": round(expected_benefit, 3),
        "top_feature_importances": importances[:5],
        # The main recipe also retrieves similar historical patients for case-based
        # evidence. Omitted here because it requires a vector similarity search
        # over the training dataset (e.g., using FAISS or DynamoDB + cosine similarity).
        # In production, this is essential for clinician trust.
    }


def _translate_factor(feature_name: str, value: float, importance: float) -> str:
    """Convert a feature name and value into a clinician-readable statement."""
    translations = {
        "tumor_volume_ratio": f"Tumor volume at {value*100:.0f}% of baseline",
        "parotid_left_dose": f"Left parotid at {value*100:.0f}% of tolerance",
        "parotid_right_dose": f"Right parotid at {value*100:.0f}% of tolerance",
        "spinal_cord_dose": f"Spinal cord at {value*100:.0f}% of tolerance",
        "brainstem_dose": f"Brainstem at {value*100:.0f}% of tolerance",
        "plan_age": f"Current plan is {value*TOTAL_FRACTIONS:.0f} fractions old",
        "fractions_since_replan": f"{value*TOTAL_FRACTIONS:.0f} fractions since last replan",
        "plan_conformity": f"Plan conformity index degraded to {value*2.0:.2f}",
        "dose_tracking": f"Dose delivery {'on track' if abs(value-0.5)<0.05 else 'off track'}",
        "worst_oar_fraction": f"Closest OAR at {value*100:.0f}% of tolerance",
        "weight_change": f"Patient weight change: {(value*20-10):.1f} kg from baseline",
    }
    return translations.get(feature_name, f"{feature_name}: {value:.3f} (importance: {importance:.4f})")
```

---

## Step 7: Generate Full Recommendation

*This assembles the policy query, safety check, and explanation into a complete recommendation package for the clinician dashboard.*

```python
def generate_recommendation(
    patient_state: np.ndarray,
    policy: AdaptivePlanningQNetwork,
    patient_id: str,
    fraction_number: int,
) -> Dict:
    """
    Generate a complete adaptive planning recommendation.

    This is the function called before each treatment fraction. It:
    1. Queries the policy for the recommended action.
    2. Applies safety constraints (may override the policy).
    3. Generates an explanation of the recommendation.
    4. Packages everything for the clinician dashboard.

    Args:
        patient_state: Normalized state vector (18 features).
        policy: Trained Q-network.
        patient_id: Patient identifier (for audit, never logged in detail).
        fraction_number: Current fraction number (1-35).

    Returns:
        Structured recommendation dictionary.
    """
    # Get the policy's raw recommendation.
    action_index = policy.get_action(patient_state)
    recommended_action = ACTIONS[action_index]

    # Apply safety constraints (may override).
    safe_action, violations = check_safety_constraints(patient_state, recommended_action)
    safe_action_index = ACTIONS.index(safe_action)

    # Compute confidence for the safe action.
    confidence = policy.get_action_confidence(patient_state, safe_action_index)

    # If safety overrode the policy, set confidence to 0 (signals override to clinician).
    # Note: 0.0 here means "safety override in effect," NOT "system has no idea."
    # Dashboard consumers should check safety_overridden=True first.
    if safe_action != recommended_action:
        confidence = 0.0

    # Generate explanation.
    explanation = generate_explanation(patient_state, policy, safe_action_index)

    recommendation = {
        "recommendation_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "patient_id": patient_id,
        "fraction_number": fraction_number,
        "recommended_action": safe_action,
        "confidence": round(confidence, 3),
        "policy_original_action": recommended_action,
        "safety_overridden": safe_action != recommended_action,
        "safety_violations": violations,
        "explanation": explanation,
    }

    return recommendation
```

---

## Step 8: Store Recommendation in DynamoDB

*Every recommendation gets stored for audit trail and feedback loop purposes. This is essential for HIPAA compliance and for building the dataset that improves the policy over time.*

```python
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION, config=BOTO3_RETRY_CONFIG)


def store_recommendation(recommendation: Dict) -> None:
    """
    Store a recommendation in DynamoDB for audit trail.

    Every recommendation is stored regardless of whether the clinician
    accepts it. This creates the feedback loop: we can later analyze
    which recommendations were followed and correlate with outcomes.

    DynamoDB gotcha: floats must be stored as Decimal. boto3 will
    raise TypeError on raw Python floats.
    """
    table = dynamodb.Table(RECOMMENDATION_TABLE)

    item = {
        "recommendation_id": recommendation["recommendation_id"],
        "timestamp": recommendation["timestamp"],
        "patient_id": recommendation["patient_id"],
        "fraction_number": recommendation["fraction_number"],
        "recommended_action": recommendation["recommended_action"],
        "confidence": Decimal(str(recommendation["confidence"])),
        "safety_overridden": recommendation["safety_overridden"],
        "safety_violations": recommendation["safety_violations"],
        "policy_original_action": recommendation["policy_original_action"],
        "clinician_decision": "PENDING",  # Updated when clinician responds
        # In production, also store explanation for audit trail:
        # "explanation": recommendation["explanation"],
        # Omitted here to keep the DynamoDB item simple for demonstration.
    }

    table.put_item(Item=item)
    logger.info("Stored recommendation %s for fraction %d",
                recommendation["recommendation_id"], recommendation["fraction_number"])
```

---

## Full Pipeline: Training and Inference Demo

*This assembles all the pieces into a runnable demonstration. It generates synthetic treatment trajectories (since we obviously can't use real patient data in an example), trains a CQL policy, and generates sample recommendations for a simulated patient mid-treatment.*

```python
def simulate_tumor_dynamics(
    fraction: int,
    current_volume_ratio: float,
    dose_delivered: float,
    response_rate: float,
) -> float:
    """
    Simplified tumor response model.

    Real tumor dynamics follow the linear-quadratic model with repopulation.
    This is a gross simplification that captures the general shape:
    tumors shrink with dose, with patient-specific response rates,
    plus some stochastic variation.
    """
    # Very simplified shrinkage (NOT a linear-quadratic model).
    # Real LQ model uses alpha/beta ratios and accounts for repopulation.
    kill_fraction = response_rate * (dose_delivered / TOTAL_PRESCRIBED_DOSE_GY)
    new_ratio = current_volume_ratio * (1.0 - kill_fraction * 0.02)
    # Add noise (biology is stochastic).
    new_ratio += np.random.normal(0, 0.005)
    return max(0.1, min(1.2, new_ratio))


def generate_synthetic_trajectories(
    num_patients: int = 300,
) -> List[List[Dict]]:
    """
    Generate synthetic radiation treatment trajectories for demonstration.

    Each trajectory represents one patient's full treatment course (35 fractions).
    We simulate: tumor shrinkage, OAR dose accumulation, plan degradation over time,
    and clinician replanning decisions (the behavior policy).

    This is NOT a validated radiobiological model. It produces data in the right
    shape for the RL algorithm to train on. Real data comes from treatment planning
    system exports and record-and-verify system logs.
    """
    trajectories = []

    for patient_idx in range(num_patients):
        # Patient-specific parameters.
        response_rate = np.random.uniform(0.3, 0.9)  # How responsive is this tumor
        weight_loss_rate = np.random.uniform(0, 0.3)  # kg per fraction
        plan_degradation_rate = np.random.uniform(0.001, 0.01)  # How fast plan quality drops

        # Initial state.
        tumor_volume_ratio = 1.0
        cumulative_ptv_dose = 0.0
        cumulative_oar_doses = {
            "spinal_cord": 0.0, "parotid_left": 0.0, "parotid_right": 0.0,
            "brainstem": 0.0, "optic_nerve": 0.0,
        }
        weight_change = 0.0
        conformity = 1.0 + np.random.uniform(0, 0.1)
        homogeneity = np.random.uniform(0.05, 0.15)
        last_replan_fraction = 0
        plan_start_fraction = 0

        trajectory = []

        for fraction in range(1, TOTAL_FRACTIONS + 1):
            # Build current state.
            volume_change_rate = -response_rate * 0.01  # Simplified trend
            state = build_state_vector(
                fraction_number=fraction,
                tumor_volume_ratio=tumor_volume_ratio,
                tumor_volume_change_rate=volume_change_rate,
                cumulative_ptv_dose_gy=cumulative_ptv_dose,
                cumulative_oar_doses=cumulative_oar_doses,
                plan_conformity_index=conformity,
                plan_homogeneity_index=homogeneity,
                patient_weight_change_kg=weight_change,
                fractions_since_replan=fraction - last_replan_fraction,
                current_plan_age_fractions=fraction - plan_start_fraction,
            )

            # Simulate clinician behavior policy (what historically happened).
            # Clinicians replan at fixed intervals or when they notice problems.
            action = "continue"
            if fraction == 15 and np.random.random() < 0.4:
                action = "replan"  # Some centers replan at fraction 15
            elif fraction == 25 and np.random.random() < 0.3:
                action = "replan"  # Some replan again at fraction 25
            elif max(cumulative_oar_doses.values()) / max(OAR_TOLERANCES.values()) > 0.8:
                if np.random.random() < 0.6:
                    action = "replan"  # Replan when OAR doses get high

            action_index = ACTIONS.index(action)

            # Simulate treatment delivery and response.
            fraction_dose = PRESCRIBED_DOSE_PER_FRACTION_GY
            cumulative_ptv_dose += fraction_dose

            # OAR doses accumulate (with some variation based on plan quality).
            for oar in cumulative_oar_doses:
                # Each OAR gets a fraction of the target dose (depends on geometry).
                oar_fraction_of_target = {
                    "spinal_cord": 0.55, "parotid_left": 0.35, "parotid_right": 0.30,
                    "brainstem": 0.40, "optic_nerve": 0.25,
                }[oar]
                oar_dose_this_fraction = fraction_dose * oar_fraction_of_target
                # Plan degradation increases OAR dose over time.
                degradation_factor = 1.0 + plan_degradation_rate * (fraction - plan_start_fraction)
                cumulative_oar_doses[oar] += oar_dose_this_fraction * degradation_factor

            # Tumor responds.
            tumor_volume_ratio = simulate_tumor_dynamics(
                fraction, tumor_volume_ratio, cumulative_ptv_dose, response_rate
            )

            # Plan quality degrades over time (anatomy shifts).
            conformity += plan_degradation_rate * np.random.uniform(0.5, 1.5)
            homogeneity += plan_degradation_rate * 0.5 * np.random.uniform(0.5, 1.5)

            # Weight loss.
            weight_change -= weight_loss_rate * np.random.uniform(0.5, 1.5)

            # If replanned, reset plan quality.
            if action == "replan":
                conformity = 1.0 + np.random.uniform(0, 0.05)
                homogeneity = np.random.uniform(0.05, 0.10)
                last_replan_fraction = fraction
                plan_start_fraction = fraction
                # Replanning also reduces OAR dose rates going forward.
                plan_degradation_rate *= 0.7

            # Build next state.
            next_state = build_state_vector(
                fraction_number=min(fraction + 1, TOTAL_FRACTIONS),
                tumor_volume_ratio=tumor_volume_ratio,
                tumor_volume_change_rate=volume_change_rate,
                cumulative_ptv_dose_gy=cumulative_ptv_dose,
                cumulative_oar_doses=cumulative_oar_doses,
                plan_conformity_index=conformity,
                plan_homogeneity_index=homogeneity,
                patient_weight_change_kg=weight_change,
                fractions_since_replan=fraction - last_replan_fraction,
                current_plan_age_fractions=fraction - plan_start_fraction,
            )

            # Compute reward.
            reward = compute_reward(state, action, next_state)

            trajectory.append({
                "state": state,
                "action_index": action_index,
                "reward": reward,
                "next_state": next_state,
                "done": (fraction == TOTAL_FRACTIONS),
            })

        trajectories.append(trajectory)

    return trajectories


def run_demo():
    """
    Full demonstration: generate data, train policy, produce recommendations.
    """
    print("=" * 70)
    print("Radiation Therapy Adaptive Planning: CQL Training Demo")
    print("=" * 70)

    # Step 1: Generate synthetic training data.
    print("\n[1/3] Generating synthetic treatment trajectories...")
    trajectories = generate_synthetic_trajectories(num_patients=300)
    total_transitions = sum(len(t) for t in trajectories)
    print(f"  Generated {len(trajectories)} patient trajectories ({total_transitions} transitions)")

    # Step 2: Train the CQL policy.
    print("\n[2/3] Training CQL policy...")
    policy = train_cql_policy(trajectories, num_epochs=60, batch_size=64)
    print("  Training complete.")

    # Step 3: Simulate a patient mid-treatment and generate recommendations.
    print("\n[3/3] Generating sample recommendations for a patient at fraction 18...")

    # This patient has a fast-responding tumor but the left parotid is getting hot.
    sample_state = build_state_vector(
        fraction_number=18,
        tumor_volume_ratio=0.68,            # Tumor shrunk 32% (good response)
        tumor_volume_change_rate=-0.015,    # Still shrinking
        cumulative_ptv_dose_gy=36.0,        # 18 fractions * 2 Gy = 36 Gy delivered
        cumulative_oar_doses={
            "spinal_cord": 22.0,    # 49% of 45 Gy tolerance
            "parotid_left": 22.5,   # 87% of 26 Gy tolerance (concerning!)
            "parotid_right": 16.0,  # 62% of 26 Gy tolerance
            "brainstem": 18.0,      # 33% of 54 Gy tolerance
            "optic_nerve": 10.0,    # 19% of 54 Gy tolerance
        },
        plan_conformity_index=1.25,         # Degraded from initial 1.05
        plan_homogeneity_index=0.18,        # Degraded from initial 0.08
        patient_weight_change_kg=-3.2,      # Lost 3.2 kg
        fractions_since_replan=18,          # Never replanned (initial plan still running)
        current_plan_age_fractions=18,
    )

    recommendation = generate_recommendation(
        patient_state=sample_state,
        policy=policy,
        patient_id="DEMO-HN-PATIENT-001",
        fraction_number=18,
    )

    print("\n" + "=" * 70)
    print("RECOMMENDATION OUTPUT")
    print("=" * 70)
    # Remove patient_id from display (PHI safety).
    display_rec = {k: v for k, v in recommendation.items() if k != "patient_id"}
    print(json.dumps(display_rec, indent=2, default=str))

    # Show what would happen if we query at a later fraction without replanning.
    print("\n" + "-" * 70)
    print("What if we ignore the recommendation and continue to fraction 25?")
    print("-" * 70)

    later_state = build_state_vector(
        fraction_number=25,
        tumor_volume_ratio=0.52,
        tumor_volume_change_rate=-0.008,
        cumulative_ptv_dose_gy=50.0,
        cumulative_oar_doses={
            "spinal_cord": 31.0,
            "parotid_left": 27.5,   # EXCEEDED 26 Gy tolerance!
            "parotid_right": 22.0,
            "brainstem": 25.0,
            "optic_nerve": 14.0,
        },
        plan_conformity_index=1.45,
        plan_homogeneity_index=0.25,
        patient_weight_change_kg=-5.1,
        fractions_since_replan=25,
        current_plan_age_fractions=25,
    )

    later_recommendation = generate_recommendation(
        patient_state=later_state,
        policy=policy,
        patient_id="DEMO-HN-PATIENT-001",
        fraction_number=25,
    )

    display_later = {k: v for k, v in later_recommendation.items() if k != "patient_id"}
    print(json.dumps(display_later, indent=2, default=str))

    if later_recommendation["safety_overridden"]:
        print("\n  ^ SAFETY OVERRIDE: The policy was overridden by hard constraints.")
        print("    This is exactly the scenario adaptive planning prevents.")


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This example runs. It trains a policy on synthetic data and produces recommendations with explanations and safety checks. But the distance between this demo and something you'd integrate with a treatment planning system is vast. Here's where that gap lives:

**Real data, not synthetic.** The synthetic trajectories above are a toy. Real data comes from treatment planning system (TPS) exports: DICOM RT structures, dose-volume histograms, daily CBCT registrations, and record-and-verify system logs. Extracting, aligning, and cleaning this data across systems that weren't designed to talk to each other is 80% of the engineering effort. Every institution's data pipeline is different.

**Physics-accurate dose calculation.** This example treats dose accumulation as simple addition. Real dose calculation requires Monte Carlo simulation or pencil-beam algorithms that account for tissue heterogeneity, beam geometry, and scatter. The state extraction step needs access to a dose calculation engine (or pre-computed dose distributions from the TPS).

**Validated tumor response models.** The `simulate_tumor_dynamics` function here is a cartoon. Real tumor response modeling uses the linear-quadratic model with parameters (alpha/beta ratios) that vary by tumor type, repopulation kinetics, and individual patient biology. Calibrating these models from imaging data is an active research area.

**Deformable image registration.** Tracking tumor volume and OAR positions across fractions requires deformable image registration (DIR): aligning daily CBCT to the planning CT while accounting for anatomical deformation. DIR is imperfect, especially in regions with large deformations (neck, abdomen). Errors in DIR propagate directly into state estimation errors.

**Integration with treatment planning systems.** The recommendation needs to flow into the clinical workflow. That means integration with commercial TPS software (Varian Eclipse, Elekta Monaco, RayStation) via their APIs or DICOM interfaces. These integrations are vendor-specific, often poorly documented, and require institutional IT approval.

**Offline policy evaluation.** Before deploying any policy, you need rigorous off-policy evaluation on held-out patients. This example skips it. In practice, you'd implement importance-weighted estimators and fitted Q-evaluation, and require multiple OPE methods to agree before trusting the result.

**Multi-site validation.** A policy trained on head-and-neck patients at one institution may not generalize to another institution's patient population, contouring practices, or treatment protocols. Multi-site validation studies are essential before any claim of generalizability.

**Error handling and retries.** Every AWS API call assumes success. Production wraps each call in try/except with specific handling for throttling, service errors, and validation failures. The inference path (Lambda) needs graceful degradation: if the model endpoint is unavailable, the system should clearly indicate "no recommendation available" rather than crashing.

**Structured logging.** The print statements are placeholders. Production uses structured JSON logging with consistent fields: recommendation_id, fraction_number, action, confidence, latency, model_version. Never log PHI (patient identifiers, dose values, imaging data).

**IAM least-privilege.** The inference Lambda needs exactly: `dynamodb:GetItem` on the state table, `dynamodb:PutItem` on the recommendation table, and access to the model artifact in S3 (or `sagemaker:InvokeEndpoint` if using a SageMaker endpoint). Not `dynamodb:*`. Not `s3:*`.

**VPC and encryption.** All components run in a VPC with private subnets. VPC endpoints for DynamoDB, S3, and SageMaker keep traffic off the public internet. KMS customer-managed keys encrypt all data at rest. Treatment data is PHI; it never touches the public internet.

**Regulatory pathway.** An RL agent that recommends treatment plan modifications is almost certainly a medical device under FDA regulation. The path to clearance (likely De Novo or 510(k)) requires clinical evidence of safety and effectiveness. That means prospective clinical trials, which take years. This is the actual bottleneck, not the software.

**Clinician trust and workflow integration.** The recommendation needs to appear at the right moment in the clinical workflow (before the physicist reviews the daily setup), in the right format (integrated with the TPS display, not a separate dashboard), with the right level of detail (enough to inform, not so much that it overwhelms). Getting this UX right requires extensive clinician co-design.

**Continuous monitoring.** Once deployed, track acceptance rates, override reasons, and (eventually) patient outcomes. A sudden drop in acceptance rate signals either policy drift or a change in clinical practice. Alert on anomalies. Retrain periodically as new outcome data accumulates.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 15.9](chapter15.09-radiation-therapy-adaptive-planning) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
