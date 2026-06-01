# Recipe 15.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the concepts from Recipe 15.8. It demonstrates the shape of a chemotherapy dose optimization system using offline reinforcement learning. It is absolutely not production-ready, not clinically validated, and not something you would deploy anywhere near a patient. Think of it as a learning tool: code you can run to understand how the pieces fit together. A starting point for research, not a destination for clinical use.

---

## Setup

You'll need these packages:

```bash
pip install boto3 numpy
```

For the RL training components, you'll also want:

```bash
pip install torch
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role needs: `sagemaker:CreateTrainingJob`, `sagemaker:CreateEndpoint`, `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`.

This example runs locally for demonstration. In practice, the training step runs on SageMaker with GPU instances, and the inference step runs behind a SageMaker endpoint.

---

## Config and Constants

Before we get to the logic, here's the configuration that drives the entire system. These constants encode clinical knowledge and value judgments. The reward weights in particular are not learned parameters; they're decisions made by oncologists about how to balance efficacy against toxicity. Different institutions might set them differently, and that's fine.

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
# Never log PHI (patient identifiers, lab values, diagnosis text).
# Log operational metrics only: counts, latencies, error types.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- AWS Configuration ---
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
AWS_REGION = "us-east-1"

# --- Clinical Constants ---
# These define the state space boundaries and safety thresholds.
# They come from oncology guidelines (NCCN, ASCO) and institutional protocols.

# Absolute neutrophil count thresholds (cells/microL)
ANC_HOLD_THRESHOLD = 1000       # Below this: hold treatment entirely
ANC_REDUCE_THRESHOLD = 1500     # Below this: consider dose reduction

# Platelet thresholds (cells/microL)
PLT_HOLD_THRESHOLD = 50000      # Below this: hold treatment
PLT_REDUCE_THRESHOLD = 75000    # Below this: max 50% dose

# Bilirubin threshold (mg/dL). Upper limit of normal is ~1.2.
BILIRUBIN_ULN = 1.2

# ECOG Performance Status: 0 = fully active, 4 = completely disabled
MAX_ECOG_FOR_TREATMENT = 2      # ECOG 3+ generally too poor for cytotoxic chemo

# --- Reward Function Weights ---
# These encode the efficacy-toxicity tradeoff. They are clinical value judgments.
# A more aggressive oncologist might increase TUMOR_WEIGHT.
# A more conservative one might increase TOXICITY_PENALTIES.
TUMOR_WEIGHT = 10.0
MODERATE_TOXICITY_PENALTY = 3.0     # Grade 3 adverse event
SEVERE_TOXICITY_PENALTY = 15.0      # Grade 4 adverse event (life-threatening)
DISCONTINUATION_PENALTY = 25.0      # Treatment had to stop entirely
DOSE_INTENSITY_BONUS = 1.0          # Maintaining >= 85% relative dose intensity

# --- Action Space ---
# Discrete dose levels as fractions of protocol dose.
# In practice, oncologists think in these increments.
DOSE_LEVELS = [0.0, 0.25, 0.50, 0.75, 1.0]

# Delay options (days). 0 = on schedule.
DELAY_OPTIONS = [0, 7, 14]

# G-CSF (growth factor support) options.
GCSF_OPTIONS = [False, True]

# Total number of discrete actions:
# 5 dose levels * 3 delay options * 2 G-CSF options = 30 actions
NUM_ACTIONS = len(DOSE_LEVELS) * len(DELAY_OPTIONS) * len(GCSF_OPTIONS)

# --- State Space ---
# 13 features representing what the clinician knows at decision time.
STATE_DIM = 13

# --- Training Hyperparameters ---
GAMMA = 0.99            # Discount factor (value future rewards almost as much as immediate)
CQL_ALPHA = 1.0         # CQL conservatism weight (higher = more conservative)
LEARNING_RATE = 3e-4
BATCH_SIZE = 64
NUM_EPOCHS = 100
EVAL_INTERVAL = 10

# --- DynamoDB Table Names ---
STATE_TABLE = "chemo-dose-patient-states"
RECOMMENDATION_TABLE = "chemo-dose-recommendations"
```

---

## Step 1: Define the State Representation

*The main recipe describes a 13-feature state vector capturing labs, tumor status, toxicity, and patient characteristics. This step builds that vector from raw clinical data.*

```python
def build_state_vector(
    anc: float,
    platelets: float,
    hemoglobin: float,
    creatinine: float,
    bilirubin: float,
    tumor_size: Optional[float],
    max_toxicity_grade: int,
    cycle_number: int,
    cumulative_dose_fraction: float,
    days_since_last_treatment: int,
    age: int,
    bsa: float,
    ecog_status: int,
) -> np.ndarray:
    """
    Construct a normalized state vector from raw clinical values.

    Each feature is scaled to roughly [0, 1] range so the neural network
    doesn't have to deal with wildly different magnitudes (ANC in thousands
    vs. bilirubin in single digits).

    Args:
        anc: Absolute neutrophil count (cells/microL, typical range 1500-8000)
        platelets: Platelet count (cells/microL, typical range 150000-400000)
        hemoglobin: Hemoglobin (g/dL, typical range 12-17)
        creatinine: Serum creatinine (mg/dL, typical range 0.6-1.2)
        bilirubin: Total bilirubin (mg/dL, typical range 0.1-1.2)
        tumor_size: Longest diameter in mm (None if no recent imaging)
        max_toxicity_grade: Worst CTCAE grade since last cycle (0-4)
        cycle_number: Which treatment cycle (1-based)
        cumulative_dose_fraction: Total dose given / total planned dose (0-1)
        days_since_last_treatment: Days since last chemo administration
        age: Patient age in years
        bsa: Body surface area in m^2
        ecog_status: ECOG performance status (0-4)

    Returns:
        Numpy array of shape (13,) with normalized features.
    """
    # Normalize each feature to approximately [0, 1].
    # These normalization constants come from typical clinical ranges.
    state = np.array([
        anc / 8000.0,                           # ANC: 0-8000 typical
        platelets / 400000.0,                   # Platelets: 0-400K typical
        hemoglobin / 17.0,                      # Hgb: 0-17 typical
        creatinine / 3.0,                       # Creat: 0-3 covers most patients
        bilirubin / 5.0,                        # Bili: 0-5 covers most patients
        (tumor_size or 0.0) / 100.0,            # Tumor: 0-100mm typical
        max_toxicity_grade / 4.0,               # Toxicity: 0-4 scale
        min(cycle_number, 12) / 12.0,           # Cycle: cap at 12 for normalization
        cumulative_dose_fraction,               # Already 0-1
        min(days_since_last_treatment, 42) / 42.0,  # Days: cap at 6 weeks
        age / 100.0,                            # Age: 0-100
        bsa / 2.5,                              # BSA: 0-2.5 m^2 typical
        ecog_status / 4.0,                      # ECOG: 0-4
    ], dtype=np.float32)

    return state
```

---

## Step 2: Define the Action Space Encoding

*The action space is discrete: combinations of dose level, delay, and G-CSF. This step maps between action indices (what the neural network outputs) and clinical actions (what the oncologist sees).*

```python
def action_index_to_clinical(action_index: int) -> Dict:
    """
    Convert a flat action index (0 to NUM_ACTIONS-1) into a clinical action.

    The action space is the Cartesian product of:
    - 5 dose levels: [0%, 25%, 50%, 75%, 100%]
    - 3 delay options: [0, 7, 14 days]
    - 2 G-CSF options: [no, yes]

    We flatten this into a single integer for the Q-network.

    Args:
        action_index: Integer in [0, 29]

    Returns:
        Dictionary with dose_fraction, delay_days, and gcsf fields.
    """
    # Unflatten: action_index = dose_idx * 6 + delay_idx * 2 + gcsf_idx
    gcsf_idx = action_index % 2
    remaining = action_index // 2
    delay_idx = remaining % 3
    dose_idx = remaining // 3

    return {
        "dose_fraction": DOSE_LEVELS[dose_idx],
        "delay_days": DELAY_OPTIONS[delay_idx],
        "gcsf": GCSF_OPTIONS[gcsf_idx],
    }


def clinical_to_action_index(dose_fraction: float, delay_days: int, gcsf: bool) -> int:
    """
    Convert a clinical action back to a flat index.

    Finds the closest matching discrete action for continuous dose values.
    """
    # Find closest dose level.
    dose_idx = int(np.argmin([abs(d - dose_fraction) for d in DOSE_LEVELS]))
    # Find closest delay.
    delay_idx = int(np.argmin([abs(d - delay_days) for d in DELAY_OPTIONS]))
    # G-CSF is binary.
    gcsf_idx = 1 if gcsf else 0

    return dose_idx * 6 + delay_idx * 2 + gcsf_idx
```

---

## Step 3: Compute the Reward

*The reward function is where clinical judgment meets math. It balances tumor response against toxicity, with heavy penalties for treatment discontinuation. The weights are configurable because different oncologists have different risk tolerances.*

```python
def compute_reward(
    current_state: np.ndarray,
    action: Dict,
    next_state: np.ndarray,
    treatment_discontinued: bool,
) -> float:
    """
    Compute the reward for a single transition.

    This encodes the clinical tradeoff: we want tumor shrinkage (good),
    we want to avoid toxicity (bad), and we really want to avoid forcing
    treatment to stop entirely (very bad, because the tumor wins).

    Args:
        current_state: State vector at decision time (normalized).
        action: The clinical action taken.
        next_state: State vector at the next cycle (normalized).
        treatment_discontinued: Whether treatment had to stop after this cycle.

    Returns:
        Scalar reward value.
    """
    reward = 0.0

    # --- Tumor response component ---
    # Compare tumor size between cycles (both normalized by /100.0).
    # Shrinkage = positive reward. Growth = negative reward.
    current_tumor = current_state[5]  # index 5 = tumor_size normalized
    next_tumor = next_state[5]

    # Only compute tumor reward if both measurements exist (non-zero).
    if current_tumor > 0.01 and next_tumor > 0.01:
        # Negative change means shrinkage. Flip sign so shrinkage is positive.
        tumor_change = (next_tumor - current_tumor) / current_tumor
        reward += -1.0 * tumor_change * TUMOR_WEIGHT

    # --- Toxicity penalty ---
    # next_state[6] is max_toxicity_grade / 4.0, so multiply back.
    next_toxicity = int(round(next_state[6] * 4.0))

    if next_toxicity >= 4:
        reward -= SEVERE_TOXICITY_PENALTY
    elif next_toxicity == 3:
        reward -= MODERATE_TOXICITY_PENALTY

    # --- Treatment discontinuation penalty ---
    if treatment_discontinued:
        reward -= DISCONTINUATION_PENALTY

    # --- Dose intensity bonus ---
    # Reward maintaining therapeutic dose levels (>= 85% of protocol).
    if action["dose_fraction"] >= 0.85:
        reward += DOSE_INTENSITY_BONUS

    return reward
```

---

## Step 4: Safety Constraint Enforcement

*Hard safety constraints that override any policy recommendation. These are non-negotiable clinical rules. The RL policy optimizes within these bounds; it never gets to violate them.*

```python
def apply_safety_constraints(
    recommended_action: Dict,
    state: np.ndarray,
    cumulative_dose_limit: float = 1.0,
) -> Tuple[Dict, List[str]]:
    """
    Apply hard safety constraints to a recommended action.

    These constraints represent absolute clinical contraindications.
    No matter what the RL policy says, these rules cannot be violated.
    The policy learns to work within these bounds, not around them.

    Args:
        recommended_action: The policy's raw recommendation.
        state: Current normalized state vector.
        cumulative_dose_limit: Maximum allowed cumulative dose fraction (default 1.0).

    Returns:
        Tuple of (possibly modified action, list of violation descriptions).
    """
    # Work on a copy so we don't mutate the input.
    action = dict(recommended_action)
    violations = []

    # Denormalize the state features we need for safety checks.
    anc = state[0] * 8000.0
    platelets = state[1] * 400000.0
    bilirubin = state[4] * 5.0
    cumulative_dose = state[8]  # already 0-1
    ecog = int(round(state[12] * 4.0))

    # Rule 1: ANC critically low. Hold treatment.
    if anc < ANC_HOLD_THRESHOLD and action["dose_fraction"] > 0:
        violations.append(
            f"ANC {anc:.0f} < {ANC_HOLD_THRESHOLD}: must hold treatment"
        )
        action["dose_fraction"] = 0.0
        action["delay_days"] = 7

    # Rule 2: ANC low but not critical. Cap at 75%.
    elif anc < ANC_REDUCE_THRESHOLD and action["dose_fraction"] > 0.75:
        violations.append(
            f"ANC {anc:.0f} < {ANC_REDUCE_THRESHOLD}: max 75% dose"
        )
        action["dose_fraction"] = 0.75

    # Rule 3: Platelets critically low. Hold treatment.
    if platelets < PLT_HOLD_THRESHOLD and action["dose_fraction"] > 0:
        violations.append(
            f"Platelets {platelets:.0f} < {PLT_HOLD_THRESHOLD}: must hold treatment"
        )
        action["dose_fraction"] = 0.0
        action["delay_days"] = 7

    # Rule 4: Platelets low. Cap at 50%.
    elif platelets < PLT_REDUCE_THRESHOLD and action["dose_fraction"] > 0.5:
        violations.append(
            f"Platelets {platelets:.0f} < {PLT_REDUCE_THRESHOLD}: max 50% dose"
        )
        action["dose_fraction"] = 0.5

    # Rule 5: Elevated bilirubin (hepatic impairment). Cap at 75%.
    if bilirubin > 1.5 * BILIRUBIN_ULN and action["dose_fraction"] > 0.75:
        violations.append(
            f"Bilirubin {bilirubin:.1f} > {1.5 * BILIRUBIN_ULN:.1f}: max 75% dose"
        )
        action["dose_fraction"] = 0.75

    # Rule 6: Never exceed 100% of protocol dose.
    if action["dose_fraction"] > 1.0:
        violations.append("Cannot exceed protocol dose")
        action["dose_fraction"] = 1.0

    # Rule 7: Cumulative dose limit reached.
    if cumulative_dose >= cumulative_dose_limit:
        violations.append("Cumulative dose limit reached: discontinue")
        action["dose_fraction"] = 0.0

    # Rule 8: Performance status too poor.
    if ecog > MAX_ECOG_FOR_TREATMENT:
        violations.append(
            f"ECOG {ecog} > {MAX_ECOG_FOR_TREATMENT}: hold, reassess goals of care"
        )
        action["dose_fraction"] = 0.0

    return action, violations
```

---

## Step 5: The Q-Network (Conservative Q-Learning)

*This is the core RL component. A neural network that estimates the expected cumulative reward for each state-action pair. CQL adds a penalty that pushes down Q-values for actions not seen in the training data, preventing overconfident recommendations for untested actions.*

```python
import torch
import torch.nn as nn
import torch.optim as optim


class QNetwork(nn.Module):
    """
    Q-network for chemotherapy dose optimization.

    Takes a state vector as input, outputs Q-values for all possible actions.
    The action with the highest Q-value is the policy's recommendation.

    Architecture is intentionally simple: three hidden layers with ReLU.
    For this problem size (13 state features, 30 actions), this is sufficient.
    """

    def __init__(self, state_dim: int = STATE_DIM, num_actions: int = NUM_ACTIONS):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, num_actions),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass: state -> Q-values for all actions.

        Args:
            state: Tensor of shape (batch_size, state_dim)

        Returns:
            Tensor of shape (batch_size, num_actions) with Q-value estimates.
        """
        return self.network(state)

    def get_action(self, state: np.ndarray) -> int:
        """
        Select the best action for a single state (greedy policy).

        Args:
            state: Numpy array of shape (state_dim,)

        Returns:
            Action index with highest Q-value.
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.forward(state_tensor)
            return int(q_values.argmax(dim=1).item())

    def get_action_confidence(self, state: np.ndarray, action_index: int) -> float:
        """
        Compute a confidence score for a specific action.

        Uses softmax over Q-values as a proxy for confidence.
        High confidence = the recommended action has much higher Q-value
        than alternatives. Low confidence = multiple actions have similar Q-values.

        Args:
            state: Numpy array of shape (state_dim,)
            action_index: The action to compute confidence for.

        Returns:
            Confidence score in [0, 1].
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            q_values = self.forward(state_tensor).squeeze(0)
            # Temperature-scaled softmax. Lower temperature = sharper distribution.
            probs = torch.softmax(q_values / 2.0, dim=0)
            return float(probs[action_index].item())
```

---

## Step 6: CQL Training Loop

*Conservative Q-Learning training. The key addition over standard DQN is the CQL penalty term that discourages the policy from being overconfident about actions it hasn't seen in the historical data. This is what makes offline RL safe for healthcare: the policy stays close to what clinicians actually did.*

```python
def train_cql_policy(
    trajectories: List[List[Dict]],
    num_epochs: int = NUM_EPOCHS,
    batch_size: int = BATCH_SIZE,
    gamma: float = GAMMA,
    cql_alpha: float = CQL_ALPHA,
    lr: float = LEARNING_RATE,
) -> QNetwork:
    """
    Train a Conservative Q-Learning policy from historical trajectories.

    Each trajectory is a list of dicts with keys:
    state, action_index, reward, next_state, done.

    CQL adds a regularization term that penalizes high Q-values for
    actions not present in the dataset. This prevents the policy from
    recommending actions that were never tried historically (and whose
    outcomes are therefore unknown).

    Args:
        trajectories: List of patient treatment trajectories.
        num_epochs: Number of training epochs.
        batch_size: Mini-batch size for SGD.
        gamma: Discount factor for future rewards.
        cql_alpha: Weight of the CQL conservatism penalty.
        lr: Learning rate.

    Returns:
        Trained QNetwork.
    """
    # Flatten trajectories into a replay buffer of (s, a, r, s', done) tuples.
    replay_buffer = []
    for traj in trajectories:
        for transition in traj:
            replay_buffer.append(transition)

    logger.info(
        "Training CQL policy: %d transitions from %d trajectories",
        len(replay_buffer), len(trajectories),
    )

    if len(replay_buffer) < batch_size:
        raise ValueError(
            f"Need at least {batch_size} transitions, got {len(replay_buffer)}"
        )

    # Initialize networks.
    q_network = QNetwork()
    target_network = QNetwork()
    target_network.load_state_dict(q_network.state_dict())

    optimizer = optim.Adam(q_network.parameters(), lr=lr)

    for epoch in range(num_epochs):
        # Sample a random mini-batch.
        indices = np.random.choice(len(replay_buffer), size=batch_size, replace=False)
        batch = [replay_buffer[i] for i in indices]

        states = torch.FloatTensor(np.array([t["state"] for t in batch]))
        actions = torch.LongTensor([t["action_index"] for t in batch])
        rewards = torch.FloatTensor([t["reward"] for t in batch])
        next_states = torch.FloatTensor(np.array([t["next_state"] for t in batch]))
        dones = torch.FloatTensor([float(t["done"]) for t in batch])

        # --- Standard DQN target ---
        # Q_target = reward + gamma * max_a' Q_target(s', a') * (1 - done)
        with torch.no_grad():
            next_q_values = target_network(next_states)
            max_next_q = next_q_values.max(dim=1).values
            targets = rewards + gamma * max_next_q * (1.0 - dones)

        # Current Q-values for the actions that were actually taken.
        current_q_all = q_network(states)
        current_q = current_q_all.gather(1, actions.unsqueeze(1)).squeeze(1)

        # --- CQL penalty ---
        # Push down Q-values for ALL actions (logsumexp),
        # then push UP Q-values for actions in the dataset.
        # Net effect: out-of-distribution actions get lower Q-values.
        logsumexp_q = torch.logsumexp(current_q_all, dim=1).mean()
        data_q = current_q.mean()
        cql_loss = cql_alpha * (logsumexp_q - data_q)

        # --- Combined loss ---
        td_loss = nn.functional.mse_loss(current_q, targets)
        total_loss = td_loss + cql_loss

        optimizer.zero_grad()
        total_loss.backward()
        optimizer.step()

        # Update target network periodically (soft update).
        if epoch % 5 == 0:
            for param, target_param in zip(
                q_network.parameters(), target_network.parameters()
            ):
                target_param.data.copy_(0.95 * target_param.data + 0.05 * param.data)

        # Log progress.
        if epoch % EVAL_INTERVAL == 0:
            logger.info(
                "Epoch %d: td_loss=%.4f, cql_loss=%.4f, total=%.4f",
                epoch, td_loss.item(), cql_loss.item(), total_loss.item(),
            )

    return q_network
```

---

## Step 7: Generate a Recommendation

*Putting it all together: take a patient's current state, run it through the policy, apply safety constraints, and produce a structured recommendation for the oncologist.*

```python
def generate_recommendation(
    patient_state: np.ndarray,
    policy: QNetwork,
    patient_id: str,
) -> Dict:
    """
    Generate a complete dosing recommendation for clinician review.

    This is the function that would be called by the decision support UI.
    It runs the policy, applies safety constraints, computes confidence,
    and packages everything into a structured recommendation.

    Args:
        patient_state: Normalized state vector (13 features).
        policy: Trained QNetwork.
        patient_id: Patient identifier (for audit trail, never logged).

    Returns:
        Structured recommendation dictionary.
    """
    # Get the policy's raw recommendation.
    action_index = policy.get_action(patient_state)
    raw_action = action_index_to_clinical(action_index)

    # Apply safety constraints (may modify the action).
    safe_action, violations = apply_safety_constraints(raw_action, patient_state)

    # Recompute action index after safety modifications.
    safe_action_index = clinical_to_action_index(
        safe_action["dose_fraction"],
        safe_action["delay_days"],
        safe_action["gcsf"],
    )

    # Compute confidence.
    confidence = policy.get_action_confidence(patient_state, safe_action_index)

    # Build the protocol-based recommendation for comparison.
    protocol_action = get_protocol_recommendation(patient_state)

    # Identify key state features driving the recommendation.
    key_drivers = identify_key_drivers(patient_state, policy, safe_action_index)

    recommendation = {
        "recommendation_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "patient_id": patient_id,
        "recommended_dose_fraction": safe_action["dose_fraction"],
        "recommended_delay_days": safe_action["delay_days"],
        "recommended_gcsf": safe_action["gcsf"],
        "confidence_score": round(confidence, 3),
        "safety_violations": violations,
        "safety_constrained": len(violations) > 0,
        "protocol_recommendation": protocol_action,
        "differs_from_protocol": safe_action != protocol_action,
        "key_drivers": key_drivers,
    }

    return recommendation


def get_protocol_recommendation(state: np.ndarray) -> Dict:
    """
    Standard protocol-based dosing recommendation.

    This implements the simple rule-based approach that most oncologists
    follow today. The RL policy's value is measured against this baseline.
    """
    anc = state[0] * 8000.0
    platelets = state[1] * 400000.0
    max_tox = int(round(state[6] * 4.0))

    dose = 1.0
    delay = 0

    # Standard dose modification rules (simplified NCCN-style).
    if anc < ANC_HOLD_THRESHOLD or platelets < PLT_HOLD_THRESHOLD:
        dose = 0.0
        delay = 7
    elif anc < ANC_REDUCE_THRESHOLD or max_tox >= 3:
        dose = 0.75
    elif platelets < PLT_REDUCE_THRESHOLD:
        dose = 0.75

    return {
        "dose_fraction": dose,
        "delay_days": delay,
        "gcsf": False,  # Protocol doesn't proactively recommend G-CSF
    }


def identify_key_drivers(
    state: np.ndarray, policy: QNetwork, action_index: int
) -> List[Dict]:
    """
    Identify which state features most influence the recommendation.

    Uses a simple perturbation-based approach: for each feature, slightly
    change it and see how much the Q-value changes. Larger changes mean
    that feature is more important to the decision.
    """
    feature_names = [
        "anc", "platelets", "hemoglobin", "creatinine", "bilirubin",
        "tumor_size", "max_toxicity", "cycle_number", "cumulative_dose",
        "days_since_last", "age", "bsa", "ecog_status",
    ]

    base_q = _get_q_value(policy, state, action_index)
    importances = []

    for i, name in enumerate(feature_names):
        # Perturb feature up by 10%.
        perturbed = state.copy()
        perturbed[i] = min(perturbed[i] + 0.1, 1.0)
        perturbed_q = _get_q_value(policy, perturbed, action_index)
        importance = abs(perturbed_q - base_q)
        importances.append({"feature": name, "importance": round(importance, 4)})

    # Return top 3 most important features.
    importances.sort(key=lambda x: x["importance"], reverse=True)
    return importances[:3]


def _get_q_value(policy: QNetwork, state: np.ndarray, action_index: int) -> float:
    """Helper: get Q-value for a specific state-action pair."""
    with torch.no_grad():
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        q_values = policy(state_tensor).squeeze(0)
        return float(q_values[action_index].item())
```

---

## Step 8: Store Recommendation in DynamoDB

*Every recommendation gets stored for audit trail purposes, regardless of whether the clinician accepts it. This is essential for HIPAA compliance and for building the feedback loop that improves the policy over time.*

```python
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION, config=BOTO3_RETRY_CONFIG)


def store_recommendation(recommendation: Dict) -> None:
    """
    Store a recommendation in DynamoDB for audit trail.

    Every recommendation is stored, whether accepted or rejected.
    This creates the feedback loop: we can later analyze which
    recommendations were followed and what outcomes resulted.

    DynamoDB gotcha: floats must be stored as Decimal. boto3 will
    raise TypeError on raw Python floats.
    """
    table = dynamodb.Table(RECOMMENDATION_TABLE)

    # Convert floats to Decimal for DynamoDB.
    item = {
        "recommendation_id": recommendation["recommendation_id"],
        "timestamp": recommendation["timestamp"],
        "patient_id": recommendation["patient_id"],
        "dose_fraction": Decimal(str(recommendation["recommended_dose_fraction"])),
        "delay_days": recommendation["recommended_delay_days"],
        "gcsf": recommendation["recommended_gcsf"],
        "confidence": Decimal(str(recommendation["confidence_score"])),
        "safety_constrained": recommendation["safety_constrained"],
        "safety_violations": recommendation["safety_violations"],
        "differs_from_protocol": recommendation["differs_from_protocol"],
        "clinician_decision": "PENDING",  # Updated when clinician responds
    }

    table.put_item(Item=item)
    logger.info("Stored recommendation %s", recommendation["recommendation_id"])
```

---

## Full Pipeline: Training and Inference

*This assembles all the pieces into a runnable demonstration. It generates synthetic trajectories (since we can't use real patient data in an example), trains a CQL policy, and generates a sample recommendation.*

```python
def generate_synthetic_trajectories(num_patients: int = 200, cycles_per_patient: int = 8) -> List[List[Dict]]:
    """
    Generate synthetic treatment trajectories for demonstration.

    In a real system, these come from EHR data extraction (see Step 1 in the
    main recipe). Here we simulate plausible clinical trajectories with
    realistic dynamics: ANC drops after chemo, recovers over 2-3 weeks,
    tumors respond gradually, toxicity accumulates.

    This is NOT a validated pharmacokinetic model. It's a toy that produces
    data in the right shape for the RL algorithm to train on.
    """
    trajectories = []

    for _ in range(num_patients):
        # Initialize patient with random baseline characteristics.
        anc = np.random.uniform(4000, 8000)
        platelets = np.random.uniform(200000, 400000)
        hemoglobin = np.random.uniform(12, 16)
        creatinine = np.random.uniform(0.6, 1.2)
        bilirubin = np.random.uniform(0.3, 1.0)
        tumor_size = np.random.uniform(20, 80)
        age = np.random.randint(45, 80)
        bsa = np.random.uniform(1.5, 2.3)
        ecog = np.random.choice([0, 0, 0, 1, 1, 2])

        trajectory = []
        cumulative_dose = 0.0

        for cycle in range(cycles_per_patient):
            # Build state.
            state = build_state_vector(
                anc=anc, platelets=platelets, hemoglobin=hemoglobin,
                creatinine=creatinine, bilirubin=bilirubin,
                tumor_size=tumor_size, max_toxicity_grade=0,
                cycle_number=cycle + 1, cumulative_dose_fraction=cumulative_dose,
                days_since_last_treatment=14 if cycle > 0 else 0,
                age=age, bsa=bsa, ecog_status=ecog,
            )

            # Simulate clinician decision (behavior policy).
            if anc < ANC_HOLD_THRESHOLD:
                dose = 0.0
            elif anc < ANC_REDUCE_THRESHOLD:
                dose = 0.75
            else:
                dose = np.random.choice([0.75, 1.0], p=[0.3, 0.7])

            delay = 0 if anc >= ANC_HOLD_THRESHOLD else 7
            gcsf = anc < 2000

            action = {"dose_fraction": dose, "delay_days": delay, "gcsf": gcsf}
            action_index = clinical_to_action_index(dose, delay, gcsf)

            # Simulate patient response (very simplified dynamics).
            # ANC drops proportionally to dose, recovers partially by next cycle.
            anc_nadir = anc * (1.0 - 0.6 * dose)
            anc = anc_nadir + np.random.uniform(1000, 3000)  # recovery
            if gcsf:
                anc += 1500  # G-CSF boosts recovery

            platelets = platelets * (1.0 - 0.3 * dose) + np.random.uniform(20000, 50000)
            hemoglobin = max(8.0, hemoglobin - 0.3 * dose + np.random.uniform(-0.2, 0.2))

            # Tumor responds to treatment (slowly).
            if dose > 0:
                tumor_size = tumor_size * (1.0 - 0.05 * dose) + np.random.uniform(-2, 2)
                tumor_size = max(5.0, tumor_size)

            cumulative_dose += dose / cycles_per_patient

            # Determine toxicity grade (simplified).
            max_tox = 0
            if anc_nadir < 500:
                max_tox = 4
            elif anc_nadir < 1000:
                max_tox = 3
            elif anc_nadir < 1500:
                max_tox = 2

            # Build next state.
            next_state = build_state_vector(
                anc=anc, platelets=platelets, hemoglobin=hemoglobin,
                creatinine=creatinine, bilirubin=bilirubin,
                tumor_size=tumor_size, max_toxicity_grade=max_tox,
                cycle_number=cycle + 2, cumulative_dose_fraction=cumulative_dose,
                days_since_last_treatment=14 + delay,
                age=age, bsa=bsa, ecog_status=ecog,
            )

            # Compute reward.
            discontinued = False
            reward = compute_reward(state, action, next_state, discontinued)

            trajectory.append({
                "state": state,
                "action_index": action_index,
                "reward": reward,
                "next_state": next_state,
                "done": (cycle == cycles_per_patient - 1),
            })

        trajectories.append(trajectory)

    return trajectories


def run_demo():
    """
    Full demonstration: generate data, train policy, produce recommendation.
    """
    print("=" * 60)
    print("Chemotherapy Dose Optimization: CQL Training Demo")
    print("=" * 60)

    # Step 1: Generate synthetic training data.
    print("\n[1/3] Generating synthetic treatment trajectories...")
    trajectories = generate_synthetic_trajectories(num_patients=200, cycles_per_patient=8)
    total_transitions = sum(len(t) for t in trajectories)
    print(f"  Generated {len(trajectories)} trajectories ({total_transitions} transitions)")

    # Step 2: Train the CQL policy.
    print("\n[2/3] Training CQL policy...")
    policy = train_cql_policy(trajectories, num_epochs=50, batch_size=64)
    print("  Training complete.")

    # Step 3: Generate a sample recommendation.
    print("\n[3/3] Generating sample recommendation...")
    sample_state = build_state_vector(
        anc=1800, platelets=145000, hemoglobin=11.2,
        creatinine=0.9, bilirubin=0.8, tumor_size=45.0,
        max_toxicity_grade=2, cycle_number=4,
        cumulative_dose_fraction=0.45, days_since_last_treatment=14,
        age=67, bsa=1.85, ecog_status=1,
    )

    recommendation = generate_recommendation(
        patient_state=sample_state,
        policy=policy,
        patient_id="DEMO-PATIENT-001",
    )

    print("\n" + "=" * 60)
    print("RECOMMENDATION OUTPUT")
    print("=" * 60)
    # Remove patient_id from display (PHI safety in logs).
    display_rec = {k: v for k, v in recommendation.items() if k != "patient_id"}
    print(json.dumps(display_rec, indent=2, default=str))

    # Show what protocol would recommend for comparison.
    print("\n--- Protocol-based recommendation (baseline) ---")
    print(json.dumps(recommendation["protocol_recommendation"], indent=2))

    if recommendation["differs_from_protocol"]:
        print("\n  ^ Policy DIFFERS from protocol. Review key drivers above.")
    else:
        print("\n  ^ Policy AGREES with protocol for this patient state.")


if __name__ == "__main__":
    run_demo()
```

---

## The Gap Between This and Production

This example runs. It trains a policy on synthetic data and produces a recommendation. But the distance between this demo and something you'd put in front of an oncologist is enormous. Here's where that gap lives:

**Real data, not synthetic.** The synthetic trajectories above are a toy. Real trajectories come from EHR extraction: joining medication administration records, lab results, imaging reports, and toxicity documentation across irregular time intervals. That ETL pipeline (AWS Glue in the main recipe) is 80% of the engineering effort. Missing data, inconsistent documentation, and temporal misalignment are the norm, not the exception.

**Offline policy evaluation.** Before deploying any policy, you need rigorous off-policy evaluation (OPE). This example skips it entirely. In practice, you'd implement importance-weighted evaluation and fitted Q-evaluation on held-out trajectories, and you'd require multiple OPE methods to agree before trusting the result. Disagreement between estimators is a red flag, not a tiebreaker.

**Model validation with oncologists.** The policy's recommendations need expert review on representative cases. Oncologists should see the recommendations, the reasoning, and the patient context, then flag cases where they disagree. Those disagreements are gold: they reveal either policy failures or opportunities to improve the reward function.

**SageMaker deployment.** In production, the trained model lives behind a SageMaker endpoint (not running locally). The inference path is: patient state from DynamoDB, invoke SageMaker endpoint, apply safety constraints, store recommendation, display to clinician. The endpoint needs auto-scaling, monitoring, and model versioning.

**Error handling and retries.** Every AWS API call in this example assumes success. Production code wraps each call in try/except with specific handling for throttling (exponential backoff), service errors (retry with circuit breaker), and validation failures (reject and log).

**Input validation.** This code trusts its inputs. Production validates that lab values are within physiologically plausible ranges (ANC of 50,000 is a data error, not a real patient), that required fields are present, and that the state vector doesn't contain NaN or infinity values.

**Structured logging.** The print statements here are placeholders. Production uses structured JSON logging (AWS Lambda Powertools or similar) with consistent fields: request_id, latency, model_version, action_taken, confidence. Never log PHI values (lab results, patient identifiers).

**IAM least-privilege.** The IAM role for the inference Lambda needs exactly: `sagemaker:InvokeEndpoint` on the specific endpoint ARN, `dynamodb:GetItem` on the state table, `dynamodb:PutItem` on the recommendation table. Not `sagemaker:*`. Not `dynamodb:*`.

**VPC and encryption.** All components run in a VPC with private subnets. VPC endpoints for SageMaker, DynamoDB, and S3 keep traffic off the public internet. KMS customer-managed keys encrypt all data at rest. TLS encrypts all data in transit.

**Regulatory and clinical governance.** This is the biggest gap. An RL-based dosing recommendation system likely requires FDA clearance (as clinical decision support or SaMD). It requires IRB approval for the research phase, institutional governance approval for deployment, and a prospective validation study before clinical use. None of that is a software engineering problem, but it's the actual bottleneck.

**Reward function tuning.** The reward weights in this example are arbitrary. In practice, they need to be set in collaboration with oncologists, validated against clinical intuition, and potentially varied across regimens. Two equally valid weight configurations produce meaningfully different policies. Making this tradeoff explicit and configurable (not hidden) is essential for clinical trust.

**Continuous learning.** Once deployed, the system should track outcomes for patients where recommendations were followed vs. not. Over time, this builds evidence for or against the policy and enables retraining on institution-specific data. The feedback loop from DynamoDB back to S3 (shown in the architecture diagram) enables this, but the retraining pipeline, model comparison, and safe rollout process are additional engineering.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 15.8](chapter15.08-chemotherapy-dose-optimization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
