# Recipe 15.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the RL concepts from Recipe 15.10. It demonstrates the shape of a hospital resource allocation RL system: environment definition, state construction, reward shaping, constrained policy optimization, and decision support output. It is not production-ready. A real hospital resource allocator requires months of simulator calibration, extensive offline evaluation, IRB-level review of the reward function, and careful pilot deployment with human oversight at every step. Consider this a learning tool, not a deployment artifact.

---

## Setup

You'll need the following packages:

```bash
pip install boto3 numpy
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `kinesis:GetRecords`, `kinesis:PutRecord`, `s3:GetObject`, `s3:PutObject`, and `states:StartExecution`.

---

## Config and Constants

Before the logic, here's the configuration that defines the hospital domain. These constants encode operational knowledge about resource allocation: what units exist, what actions are possible, what constraints are non-negotiable, and how to score outcomes. In a real system, these would be developed with hospital operations leadership and validated against your specific facility's data.

```python
import numpy as np
import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON format for CloudWatch Logs Insights.
# Never log patient identifiers, room numbers tied to patients, or PHI values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS calls. Adaptive mode handles throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Hospital Configuration ---
# Each unit has a name, capacity, type, and minimum staffing ratio (nurses:patients).
# This models a mid-size community hospital (~250 beds). Your facility will differ.
UNITS = [
    {"name": "icu", "capacity": 20, "type": "critical", "min_ratio": 0.5},
    {"name": "stepdown", "capacity": 24, "type": "intermediate", "min_ratio": 0.33},
    {"name": "medsurg_a", "capacity": 36, "type": "general", "min_ratio": 0.2},
    {"name": "medsurg_b", "capacity": 36, "type": "general", "min_ratio": 0.2},
    {"name": "telemetry", "capacity": 28, "type": "monitored", "min_ratio": 0.25},
    {"name": "ed_holding", "capacity": 12, "type": "emergency", "min_ratio": 0.33},
]

TOTAL_BEDS = sum(u["capacity"] for u in UNITS)
NUM_UNITS = len(UNITS)

# --- Action Space ---
# Discrete actions the RL agent can recommend. Each represents a common
# resource allocation decision that bed coordinators make dozens of times daily.
ACTION_SPACE = [
    "no_action",                        # 0: hold, no change needed right now
    "assign_ed_boarder_medsurg_a",      # 1: move ED boarder to med-surg A
    "assign_ed_boarder_medsurg_b",      # 2: move ED boarder to med-surg B
    "assign_ed_boarder_telemetry",      # 3: move ED boarder to telemetry
    "assign_ed_boarder_stepdown",       # 4: move ED boarder to step-down
    "transfer_icu_to_stepdown",         # 5: step down an ICU patient
    "transfer_stepdown_to_medsurg",     # 6: move step-down patient to floor
    "float_nurse_to_icu",              # 7: float a nurse from low-acuity unit to ICU
    "float_nurse_to_ed",               # 8: float a nurse to ED
    "activate_overflow",               # 9: open overflow beds (high cost)
    "request_early_discharge_review",  # 10: flag patients for expedited discharge
    "hold_or_bed_for_post_op",         # 11: reserve bed for upcoming OR case
]

NUM_ACTIONS = len(ACTION_SPACE)

# --- State Feature Definitions ---
# The state vector captures a snapshot of hospital operations.
# Features are grouped by source system and update frequency.
STATE_FEATURES = [
    # Census by unit (fraction occupied, 0.0 to 1.0+)
    {"name": "icu_occupancy", "min": 0.0, "max": 1.2},
    {"name": "stepdown_occupancy", "min": 0.0, "max": 1.2},
    {"name": "medsurg_a_occupancy", "min": 0.0, "max": 1.2},
    {"name": "medsurg_b_occupancy", "min": 0.0, "max": 1.2},
    {"name": "telemetry_occupancy", "min": 0.0, "max": 1.2},
    {"name": "ed_holding_occupancy", "min": 0.0, "max": 2.0},
    # Staffing ratios (actual / required, 1.0 = exactly at minimum)
    {"name": "icu_staff_ratio", "min": 0.5, "max": 2.0},
    {"name": "stepdown_staff_ratio", "min": 0.5, "max": 2.0},
    {"name": "medsurg_staff_ratio", "min": 0.5, "max": 2.0},
    {"name": "telemetry_staff_ratio", "min": 0.5, "max": 2.0},
    {"name": "ed_staff_ratio", "min": 0.5, "max": 2.0},
    # Pending movements (counts, normalized by capacity)
    {"name": "ed_boarders_waiting", "min": 0, "max": 15},
    {"name": "pending_admissions", "min": 0, "max": 10},
    {"name": "pending_discharges_confirmed", "min": 0, "max": 20},
    {"name": "pending_discharges_probable", "min": 0, "max": 20},
    {"name": "or_cases_remaining_today", "min": 0, "max": 15},
    # Equipment availability (fraction available)
    {"name": "ventilators_available_frac", "min": 0.0, "max": 1.0},
    {"name": "monitors_available_frac", "min": 0.0, "max": 1.0},
    # Time features (cyclical encoding)
    {"name": "hour_sin", "min": -1.0, "max": 1.0},
    {"name": "hour_cos", "min": -1.0, "max": 1.0},
    {"name": "dow_sin", "min": -1.0, "max": 1.0},
    {"name": "dow_cos", "min": -1.0, "max": 1.0},
    {"name": "is_weekend", "min": 0, "max": 1},
    {"name": "minutes_to_shift_change", "min": 0, "max": 720},
]

NUM_STATE_FEATURES = len(STATE_FEATURES)

# --- Reward Weights ---
# These encode organizational priorities. Getting alignment on these weights
# is a political process as much as a technical one. The ED director, surgical
# chief, CNO, and CFO will all have opinions. Document the rationale for each.
REWARD_WEIGHTS = {
    "ed_boarding_per_hour": -2.0,        # each hour a patient boards in ED
    "surgical_cancellation": -50.0,      # per cancelled surgical case
    "staffing_ratio_violation": -10.0,   # per unit-hour below minimum ratio
    "patient_transfer": -1.0,            # per intra-hospital transfer (disruption)
    "overtime_hour": -3.0,               # per staff overtime hour incurred
    "census_balance_bonus": 1.0,         # reward for even distribution across units
    "discharge_before_noon": 2.0,        # each discharge completed before noon
}

# --- Hard Constraints (Non-Negotiable) ---
# These are enforced at action selection time. The policy NEVER gets to violate these,
# regardless of what the neural network outputs. Think of these as the guardrails
# that prevent the system from recommending anything dangerous or illegal.
HARD_CONSTRAINTS = {
    "min_staffing_ratio": True,          # never recommend action that drops below minimum
    "max_unit_capacity": True,           # never exceed licensed bed count
    "isolation_requirements": True,      # never place infectious patient in shared room
    "equipment_availability": True,      # never assign bed requiring equipment that's out
}

# --- Training Hyperparameters ---
TRAINING_CONFIG = {
    "algorithm": "PPO",
    "learning_rate": 3e-4,
    "gamma": 0.99,                       # discount factor (long horizon)
    "gae_lambda": 0.95,                  # GAE parameter
    "clip_epsilon": 0.2,                 # PPO clipping
    "entropy_coeff": 0.01,               # exploration encouragement
    "num_episodes": 10000,
    "episode_length_hours": 24,          # simulate 24-hour periods
    "decision_interval_minutes": 30,     # recommend every 30 minutes
    "lagrange_lr": 0.01,                 # learning rate for constraint multipliers
    "constraint_thresholds": {
        "staffing_violations_per_day": 2.0,
        "capacity_overflows_per_day": 0.5,
        "ed_boarding_hours_per_day": 20.0,
    },
}
```

---

## Step 1: Build the Hospital State Vector

*The pseudocode calls this `build_state_vector(hospital_id, timestamp)`. It collects real-time data from multiple source systems and assembles a normalized feature vector representing the current hospital state.*

```python
# AWS clients for pulling operational data.
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table where we store the latest state observations from each source system.
state_table = dynamodb.Table("hospital-resource-state")


def build_state_vector(hospital_id: str, timestamp_epoch: float) -> np.ndarray:
    """
    Assemble the current hospital state into a normalized feature vector.

    In production, this pulls from multiple real-time sources:
    - ADT system (census, pending admissions/discharges)
    - Staffing platform (current levels vs. scheduled)
    - OR scheduling system (cases remaining)
    - Equipment tracking (ventilators, monitors)

    For this example, we read from a DynamoDB table that a Lambda-based
    state aggregator populates from Kinesis streams.

    Args:
        hospital_id: Identifier for the facility
        timestamp_epoch: Current time as Unix epoch seconds

    Returns:
        Normalized numpy array of shape (NUM_STATE_FEATURES,)
    """
    # Query latest state snapshot from DynamoDB.
    # The state aggregator Lambda writes here every time it processes
    # a batch of events from the Kinesis stream.
    response = state_table.get_item(
        Key={"hospital_id": hospital_id, "record_type": "current_state"}
    )

    if "Item" not in response:
        logger.warning("No current state found for hospital %s, using defaults", hospital_id)
        return np.zeros(NUM_STATE_FEATURES, dtype=np.float32)

    raw_state = response["Item"]

    # Extract and normalize each feature.
    # Normalization maps each value to roughly [0, 1] based on expected ranges.
    # This helps the neural network learn efficiently.
    features = []

    for feature_def in STATE_FEATURES:
        name = feature_def["name"]
        raw_value = float(raw_state.get(name, 0))

        # Min-max normalization to [0, 1]
        feat_min = feature_def["min"]
        feat_max = feature_def["max"]
        if feat_max > feat_min:
            normalized = (raw_value - feat_min) / (feat_max - feat_min)
            normalized = np.clip(normalized, 0.0, 1.0)
        else:
            normalized = 0.0

        features.append(normalized)

    return np.array(features, dtype=np.float32)
```

---

## Step 2: Define the Hospital Simulation Environment

*The pseudocode defines `CLASS HospitalSimulator`. This is where the RL agent trains. The simulator models patient arrivals, discharges, staff shifts, and resource consumption. Fidelity here determines whether the learned policy transfers to reality.*

```python
class HospitalSimulator:
    """
    Discrete-event simulation of hospital resource dynamics.

    This is a simplified version for illustration. A production simulator would:
    - Use fitted arrival distributions from 2+ years of ADT data
    - Model individual patient acuity trajectories
    - Include OR schedule with case-type-specific durations
    - Handle staff callouts and float pool availability
    - Model equipment maintenance cycles

    For training, we need this to be fast (thousands of episodes).
    Fidelity matters, but speed matters too. The tradeoff is: model the
    dynamics that affect resource allocation decisions, skip the details
    that don't (e.g., specific medication timing doesn't matter here).
    """

    def __init__(self, config: dict = None):
        """
        Initialize the simulator with hospital parameters.

        Args:
            config: Optional overrides for domain randomization during training.
                    Keys can override arrival rates, LOS distributions, etc.
        """
        self.config = config or {}
        self.rng = np.random.default_rng()

        # Base arrival rates (patients per hour) by unit type.
        # These get randomized during training for robustness.
        self.base_arrival_rates = self.config.get("arrival_rates", {
            "ed": 4.0,           # ~4 ED arrivals per hour requiring admission
            "direct_admit": 1.0, # direct admits (scheduled, transfers in)
            "or_post_op": 1.5,   # patients coming out of OR needing beds
        })

        # Mean length of stay by unit (hours). Log-normal in reality.
        self.mean_los_hours = self.config.get("mean_los", {
            "icu": 72,
            "stepdown": 48,
            "medsurg": 96,
            "telemetry": 72,
        })

        self.reset()

    def reset(self) -> np.ndarray:
        """
        Start a new 24-hour episode with randomized initial conditions.
        Returns the initial state vector.
        """
        # Randomize start time (hour of day affects dynamics significantly)
        self.hour = self.rng.integers(0, 24)
        self.minute = 0
        self.steps_taken = 0
        self.episode_done = False

        # Initialize census at realistic levels (60-85% occupancy)
        self.census = {}
        for unit in UNITS:
            occupancy_frac = self.rng.uniform(0.6, 0.85)
            self.census[unit["name"]] = int(unit["capacity"] * occupancy_frac)

        # Initialize staffing (some randomness around scheduled levels)
        self.staffing = {}
        for unit in UNITS:
            # Scheduled staff that would exactly meet ratio at current census
            needed = int(np.ceil(self.census[unit["name"]] * unit["min_ratio"]))
            # Actual staff: usually at or slightly above needed
            actual = needed + self.rng.integers(0, 3)
            self.staffing[unit["name"]] = actual

        # Pending queues
        self.ed_boarders = self.rng.integers(0, 5)
        self.pending_discharges = self.rng.integers(2, 8)
        self.or_cases_remaining = self.rng.integers(3, 10)

        # Equipment
        self.ventilators_total = 30
        self.ventilators_in_use = self.rng.integers(15, 25)
        self.monitors_total = 50
        self.monitors_in_use = self.rng.integers(30, 45)

        # Tracking for reward calculation
        self.ed_boarding_hours = 0.0
        self.surgical_cancellations = 0
        self.staffing_violations = 0
        self.transfers = 0
        self.overtime_hours = 0.0

        return self._get_state()

    def step(self, action: int) -> tuple:
        """
        Execute an action and advance the simulation by one decision interval.

        Args:
            action: Integer index into ACTION_SPACE

        Returns:
            (next_state, reward, done, info) tuple
        """
        info = {"constraint_violation": False}

        # Check hard constraints before executing action
        if not self._is_action_feasible(action):
            # Action violates a hard constraint. Apply penalty and skip.
            info["constraint_violation"] = True
            reward = -20.0  # strong signal: don't propose infeasible actions
            self._advance_time()
            return self._get_state(), reward, self.episode_done, info

        # Execute the action
        self._execute_action(action)

        # Advance simulation by one decision interval (30 minutes)
        self._advance_time()

        # Compute reward for this step
        reward = self._compute_reward()

        return self._get_state(), reward, self.episode_done, info

    def _is_action_feasible(self, action: int) -> bool:
        """
        Check whether an action violates any hard constraints.
        Returns True if the action is safe to execute.
        """
        action_name = ACTION_SPACE[action]

        if action_name == "no_action":
            return True

        # Check capacity constraints for bed assignment actions
        if action_name.startswith("assign_ed_boarder_"):
            target_unit = action_name.replace("assign_ed_boarder_", "")
            unit_config = next((u for u in UNITS if u["name"] == target_unit), None)
            if unit_config is None:
                return False
            # Can't assign if unit is at capacity
            if self.census.get(target_unit, 0) >= unit_config["capacity"]:
                return False
            # Can't assign if no ED boarders to move
            if self.ed_boarders <= 0:
                return False
            return True

        if action_name == "transfer_icu_to_stepdown":
            stepdown_config = next(u for u in UNITS if u["name"] == "stepdown")
            if self.census.get("stepdown", 0) >= stepdown_config["capacity"]:
                return False
            if self.census.get("icu", 0) <= 0:
                return False
            return True

        if action_name == "transfer_stepdown_to_medsurg":
            # Check if any med-surg unit has space
            for unit in UNITS:
                if unit["type"] == "general" and self.census.get(unit["name"], 0) < unit["capacity"]:
                    return True
            return False

        if action_name.startswith("float_nurse_"):
            # Can only float if source unit stays above minimum ratio
            # Simplified: check that at least one unit has surplus staff
            for unit in UNITS:
                name = unit["name"]
                current_staff = self.staffing.get(name, 0)
                needed = int(np.ceil(self.census.get(name, 0) * unit["min_ratio"]))
                if current_staff > needed + 1: # surplus of at least 1
                    return True
            return False

        # All other actions are feasible by default
        return True

    def _execute_action(self, action: int):
        """Apply the selected action to the simulation state."""
        action_name = ACTION_SPACE[action]

        if action_name == "no_action":
            return

        if action_name.startswith("assign_ed_boarder_"):
            target_unit = action_name.replace("assign_ed_boarder_", "")
            self.census[target_unit] = self.census.get(target_unit, 0) + 1
            self.ed_boarders -= 1
            self.transfers += 1

        elif action_name == "transfer_icu_to_stepdown":
            self.census["icu"] -= 1
            self.census["stepdown"] += 1
            self.transfers += 1

        elif action_name == "transfer_stepdown_to_medsurg":
            self.census["stepdown"] -= 1
            # Pick the med-surg unit with more available space
            if self.census.get("medsurg_a", 0) <= self.census.get("medsurg_b", 0):
                self.census["medsurg_a"] += 1
            else:
                self.census["medsurg_b"] += 1
            self.transfers += 1

        elif action_name == "float_nurse_to_icu":
            # Find unit with most surplus and move a nurse
            best_source = self._find_float_source()
            if best_source:
                self.staffing[best_source] -= 1
                self.staffing["icu"] = self.staffing.get("icu", 0) + 1

        elif action_name == "float_nurse_to_ed":
            best_source = self._find_float_source()
            if best_source:
                self.staffing[best_source] -= 1
                self.staffing["ed_holding"] = self.staffing.get("ed_holding", 0) + 1

        elif action_name == "activate_overflow":
            # Adds temporary capacity (expensive, disruptive)
            self.census["medsurg_a"] = self.census.get("medsurg_a", 0)  # no-op on census
            # In reality this would open a closed section
            self.overtime_hours += 4.0  # significant cost

        elif action_name == "request_early_discharge_review":
            # Probabilistically speeds up pending discharges
            if self.pending_discharges > 0 and self.rng.random() < 0.3:
                self.pending_discharges -= 1
                # Pick a random unit to discharge from
                occupied_units = [u["name"] for u in UNITS if self.census.get(u["name"], 0) > 0]
                if occupied_units:
                    unit = self.rng.choice(occupied_units)
                    self.census[unit] -= 1

        elif action_name == "hold_or_bed_for_post_op":
            # Reserves capacity. No immediate state change, but prevents
            # that bed from being assigned to an ED boarder.
            pass  # Tracked implicitly via reduced available beds

    def _find_float_source(self) -> Optional[str]:
        """Find the unit with the most staffing surplus above minimum ratio."""
        best_unit = None
        best_surplus = 0
        for unit in UNITS:
            name = unit["name"]
            current = self.staffing.get(name, 0)
            needed = int(np.ceil(self.census.get(name, 0) * unit["min_ratio"]))
            surplus = current - needed
            if surplus > best_surplus:
                best_surplus = surplus
                best_unit = name
        return best_unit

    def _advance_time(self):
        """
        Advance simulation by one decision interval (30 minutes).
        Process stochastic events: arrivals, discharges, deteriorations.
        """
        interval_hours = TRAINING_CONFIG["decision_interval_minutes"] / 60.0

        # --- Patient arrivals (Poisson process) ---
        # ED arrivals needing beds
        ed_arrivals = self.rng.poisson(
            self.base_arrival_rates["ed"] * interval_hours
        )
        self.ed_boarders += ed_arrivals

        # OR completions needing beds
        if self.or_cases_remaining > 0:
            or_completions = min(
                self.rng.poisson(self.base_arrival_rates["or_post_op"] * interval_hours),
                self.or_cases_remaining,
            )
            self.or_cases_remaining -= or_completions
            # Post-op patients need step-down or ICU beds
            for _ in range(or_completions):
                if self.rng.random() < 0.2: # 20% go to ICU
                    self.census["icu"] = self.census.get("icu", 0) + 1
                else:
                    self.census["stepdown"] = self.census.get("stepdown", 0) + 1

        # --- Patient discharges (stochastic based on pending count) ---
        if self.pending_discharges > 0:
            # Higher discharge probability during daytime hours
            discharge_prob = 0.1 if 8 <= self.hour <= 16 else 0.03
            discharges = self.rng.binomial(self.pending_discharges, discharge_prob)
            self.pending_discharges -= discharges
            # Remove patients from random occupied units
            for _ in range(discharges):
                occupied = [u["name"] for u in UNITS if self.census.get(u["name"], 0) > 0]
                if occupied:
                    unit = self.rng.choice(occupied)
                    self.census[unit] -= 1

        # --- Accumulate ED boarding penalty ---
        self.ed_boarding_hours += self.ed_boarders * interval_hours

        # --- Check staffing violations ---
        for unit in UNITS:
            name = unit["name"]
            current_staff = self.staffing.get(name, 0)
            needed = int(np.ceil(self.census.get(name, 0) * unit["min_ratio"]))
            if current_staff < needed:
                self.staffing_violations += 1

        # --- Check for surgical cancellations ---
        # If ICU and step-down are both full, OR cases can't proceed
        icu_full = self.census.get("icu", 0) >= 20
        stepdown_full = self.census.get("stepdown", 0) >= 24
        if icu_full and stepdown_full and self.or_cases_remaining > 0:
            if self.rng.random() < 0.1: # 10% chance per interval when both full
                self.surgical_cancellations += 1
                self.or_cases_remaining -= 1

        # --- Advance clock ---
        self.minute += TRAINING_CONFIG["decision_interval_minutes"]
        if self.minute >= 60:
            self.hour = (self.hour + self.minute // 60) % 24
            self.minute = self.minute % 60

        self.steps_taken += 1
        max_steps = (TRAINING_CONFIG["episode_length_hours"] * 60
                     // TRAINING_CONFIG["decision_interval_minutes"])
        if self.steps_taken >= max_steps:
            self.episode_done = True

    def _compute_reward(self) -> float:
        """
        Compute the immediate reward for the current state.
        This is called after each step to provide the training signal.
        """
        reward = 0.0

        # Penalize ED boarding (per boarder, per interval)
        interval_hours = TRAINING_CONFIG["decision_interval_minutes"] / 60.0
        reward += REWARD_WEIGHTS["ed_boarding_per_hour"] * self.ed_boarders * interval_hours

        # Penalize staffing violations
        for unit in UNITS:
            name = unit["name"]
            current_staff = self.staffing.get(name, 0)
            needed = int(np.ceil(self.census.get(name, 0) * unit["min_ratio"]))
            if current_staff < needed:
                reward += REWARD_WEIGHTS["staffing_ratio_violation"] * interval_hours

        # Reward balanced census distribution
        occupancies = []
        for unit in UNITS:
            occ = self.census.get(unit["name"], 0) / unit["capacity"]
            occupancies.append(occ)
        # Lower variance in occupancy = better balance
        balance_score = 1.0 - np.std(occupancies)
        reward += REWARD_WEIGHTS["census_balance_bonus"] * max(0, balance_score)

        return reward

    def _get_state(self) -> np.ndarray:
        """Assemble current simulation state into a normalized feature vector."""
        features = []

        # Census occupancy fractions
        for unit in UNITS:
            occ = self.census.get(unit["name"], 0) / unit["capacity"]
            features.append(np.clip(occ, 0.0, 1.2))

        # Staffing ratios (actual / minimum required)
        for unit in UNITS:
            name = unit["name"]
            current = self.staffing.get(name, 0)
            needed = max(1, int(np.ceil(self.census.get(name, 0) * unit["min_ratio"])))
            ratio = current / needed
            features.append(np.clip(ratio, 0.5, 2.0))

        # Pending queues
        features.append(float(self.ed_boarders))
        features.append(float(self.rng.integers(0, 5)))  # simplified pending admits
        features.append(float(self.pending_discharges))
        features.append(float(self.pending_discharges * 0.5))  # probable discharges
        features.append(float(self.or_cases_remaining))

        # Equipment availability
        features.append((self.ventilators_total - self.ventilators_in_use) / self.ventilators_total)
        features.append((self.monitors_total - self.monitors_in_use) / self.monitors_total)

        # Time encoding (cyclical)
        hour_frac = self.hour / 24.0
        features.append(np.sin(2 * np.pi * hour_frac))
        features.append(np.cos(2 * np.pi * hour_frac))
        # Day of week (fixed for single-episode simulation)
        dow_frac = 2 / 7.0  # pretend it's Tuesday
        features.append(np.sin(2 * np.pi * dow_frac))
        features.append(np.cos(2 * np.pi * dow_frac))
        features.append(0.0)  # is_weekend
        # Minutes to next shift change (simplified: shifts at 7, 15, 23)
        shift_hours = [7, 15, 23]
        mins_to_shift = min((sh - self.hour) % 24 * 60 - self.minute for sh in shift_hours)
        features.append(max(0, mins_to_shift) / 720.0)

        return np.array(features, dtype=np.float32)
```

---

## Step 3: Implement the RL Policy Network and Training Loop

*The pseudocode calls this `train_policy(simulator, config)`. This implements Proximal Policy Optimization (PPO) with Lagrangian constraint handling. PPO is the workhorse of modern RL: stable, well-understood, and effective with discrete action spaces.*

```python
class PolicyNetwork:
    """
    Simple feedforward policy network for the resource allocation agent.

    In production, you'd use PyTorch or TensorFlow with SageMaker's RL
    container (which bundles RLlib). This numpy-only version shows the
    structure without pulling in a heavy framework dependency.

    Architecture: state -> hidden(128) -> hidden(64) -> action logits
    """

    def __init__(self, state_dim: int, action_dim: int, hidden_size: int = 128):
        """Initialize with random weights (Xavier initialization)."""
        self.state_dim = state_dim
        self.action_dim = action_dim

        # Layer 1: state_dim -> hidden_size
        self.w1 = np.random.randn(state_dim, hidden_size) * np.sqrt(2.0 / state_dim)
        self.b1 = np.zeros(hidden_size)

        # Layer 2: hidden_size -> hidden_size // 2
        h2 = hidden_size // 2
        self.w2 = np.random.randn(hidden_size, h2) * np.sqrt(2.0 / hidden_size)
        self.b2 = np.zeros(h2)

        # Output layer: hidden -> action_dim (logits)
        self.w_out = np.random.randn(h2, action_dim) * np.sqrt(2.0 / h2)
        self.b_out = np.zeros(action_dim)

    def forward(self, state: np.ndarray) -> np.ndarray:
        """
        Forward pass: state vector -> action probabilities.

        Args:
            state: normalized state vector of shape (state_dim,)

        Returns:
            Action probability distribution of shape (action_dim,)
        """
        # Hidden layer 1 with ReLU activation
        h1 = np.maximum(0, state @ self.w1 + self.b1)
        # Hidden layer 2 with ReLU
        h2 = np.maximum(0, h1 @ self.w2 + self.b2)
        # Output logits
        logits = h2 @ self.w_out + self.b_out
        # Softmax to get probabilities
        exp_logits = np.exp(logits - np.max(logits))  # subtract max for stability
        probs = exp_logits / exp_logits.sum()
        return probs

    def select_action(self, state: np.ndarray, feasible_mask: np.ndarray) -> tuple:
        """
        Select an action, masking out infeasible actions.

        Args:
            state: current state vector
            feasible_mask: binary array where 1 = feasible, 0 = infeasible

        Returns:
            (action_index, action_probability) tuple
        """
        probs = self.forward(state)

        # Zero out infeasible actions and renormalize
        masked_probs = probs * feasible_mask
        prob_sum = masked_probs.sum()
        if prob_sum > 0:
            masked_probs = masked_probs / prob_sum
        else:
            # All actions infeasible (shouldn't happen if no_action is always feasible)
            masked_probs = feasible_mask / feasible_mask.sum()

        # Sample from the masked distribution
        action = np.random.choice(self.action_dim, p=masked_probs)
        return action, masked_probs[action]


def train_policy_loop(num_episodes: int = 1000) -> PolicyNetwork:
    """
    Train the resource allocation policy using PPO with Lagrangian constraints.

    This is a simplified training loop that demonstrates the structure.
    In production, you'd use SageMaker RL with RLlib, which handles:
    - Distributed rollout workers (multiple simulator copies in parallel)
    - GPU-accelerated policy updates
    - Proper advantage estimation (GAE)
    - Gradient-based policy optimization

    Here we show the conceptual flow: collect experience, compute rewards
    with constraint penalties, update the policy.
    """
    sim = HospitalSimulator()
    policy = PolicyNetwork(state_dim=NUM_STATE_FEATURES, action_dim=NUM_ACTIONS)

    # Lagrange multipliers for constraint costs (adaptive penalty weights)
    lambda_staffing = 1.0
    lambda_capacity = 1.0
    lambda_boarding = 1.0

    thresholds = TRAINING_CONFIG["constraint_thresholds"]
    lr_dual = TRAINING_CONFIG["lagrange_lr"]

    # Track training progress
    episode_rewards = []

    for episode in range(num_episodes):
        state = sim.reset()
        total_reward = 0.0
        episode_staffing_cost = 0.0
        episode_capacity_cost = 0.0
        episode_boarding_cost = 0.0

        while not sim.episode_done:
            # Get feasible action mask from constraint checker
            feasible_mask = np.array([
                1.0 if sim._is_action_feasible(a) else 0.0
                for a in range(NUM_ACTIONS)
            ])

            # Select action from policy (with feasibility masking)
            action, action_prob = policy.select_action(state, feasible_mask)

            # Take step in environment
            next_state, reward, done, info = sim.step(action)

            # Compute constraint costs for Lagrangian update
            step_staffing_cost = 1.0 if info.get("constraint_violation") else 0.0
            for unit in UNITS:
                name = unit["name"]
                if sim.staffing.get(name, 0) < int(np.ceil(sim.census.get(name, 0) * unit["min_ratio"])):
                    step_staffing_cost += 1.0

            step_boarding_cost = sim.ed_boarders * (TRAINING_CONFIG["decision_interval_minutes"] / 60.0)

            step_capacity_cost = 0.0
            for unit in UNITS:
                if sim.census.get(unit["name"], 0) > unit["capacity"]:
                    step_capacity_cost += 1.0

            episode_staffing_cost += step_staffing_cost
            episode_capacity_cost += step_capacity_cost
            episode_boarding_cost += step_boarding_cost

            # Augmented reward includes Lagrangian penalty terms
            augmented_reward = (
                reward
                - lambda_staffing * step_staffing_cost
                - lambda_capacity * step_capacity_cost
                - lambda_boarding * step_boarding_cost
            )

            total_reward += reward
            state = next_state

        # --- Update Lagrange multipliers (dual gradient ascent) ---
        # If constraints are violated more than threshold, increase penalty.
        # If satisfied, decrease it. This is how the policy learns to respect
        # constraints without us manually tuning penalty weights.
        lambda_staffing += lr_dual * (
            episode_staffing_cost - thresholds["staffing_violations_per_day"]
        )
        lambda_capacity += lr_dual * (
            episode_capacity_cost - thresholds["capacity_overflows_per_day"]
        )
        lambda_boarding += lr_dual * (
            episode_boarding_cost - thresholds["ed_boarding_hours_per_day"]
        )

        # Clamp to non-negative (Lagrange multipliers must be >= 0)
        lambda_staffing = max(0.0, lambda_staffing)
        lambda_capacity = max(0.0, lambda_capacity)
        lambda_boarding = max(0.0, lambda_boarding)

        episode_rewards.append(total_reward)

        # Log progress every 100 episodes
        if (episode + 1) % 100 == 0:
            avg_reward = np.mean(episode_rewards[-100:])
            logger.info(
                "Episode %d | Avg Reward: %.2f | Lambda staffing: %.3f | "
                "Lambda capacity: %.3f | Lambda boarding: %.3f",
                episode + 1, avg_reward, lambda_staffing, lambda_capacity, lambda_boarding
            )

    # NOTE: In this simplified version, we don't actually update the network weights
    # (that requires autograd / backpropagation, i.e., PyTorch or TensorFlow).
    # The structure above shows the data collection and constraint-handling logic
    # that wraps around the actual PPO update step in a real implementation.

    return policy
```

---

## Step 4: Offline Policy Evaluation

*The pseudocode calls this `evaluate_policy_offline(policy, historical_episodes)`. Before deploying any learned policy, you estimate its performance against historical data to get evidence it would do better than the status quo.*

```python
def evaluate_policy_offline(
    policy: PolicyNetwork,
    historical_data_bucket: str,
    historical_data_key: str,
) -> dict:
    """
    Evaluate a learned policy against historical hospital operations data.

    This uses a simplified form of importance-weighted evaluation: for each
    historical state, we check what our policy would have recommended vs.
    what actually happened, and estimate the reward difference.

    In production, use proper Off-Policy Evaluation (OPE) methods:
    - Fitted Q-Evaluation (FQE) for lower-variance estimates
    - Doubly-robust estimators for bias-variance tradeoff
    - Multiple OPE methods to cross-validate each other

    Args:
        policy: trained policy network
        historical_data_bucket: S3 bucket with historical episodes
        historical_data_key: S3 key prefix for evaluation data

    Returns:
        Dict with evaluation metrics and pass/fail recommendation
    """
    s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

    # Load historical episodes from S3
    response = s3_client.get_object(Bucket=historical_data_bucket, Key=historical_data_key)
    historical_episodes = json.loads(response["Body"].read().decode("utf-8"))

    results = []

    for episode in historical_episodes:
        policy_reward_estimate = 0.0
        actual_reward = 0.0
        discount = 1.0
        gamma = TRAINING_CONFIG["gamma"]

        for transition in episode["transitions"]:
            state = np.array(transition["state"], dtype=np.float32)
            actual_action = transition["action"]
            step_reward = transition["reward"]

            actual_reward += discount * step_reward

            # What would our policy have done?
            feasible_mask = np.array(transition.get("feasible_mask", np.ones(NUM_ACTIONS)))
            policy_probs = policy.forward(state) * feasible_mask
            if policy_probs.sum() > 0:
                policy_probs = policy_probs / policy_probs.sum()

            # Greedy policy action
            policy_action = int(np.argmax(policy_probs))

            # Estimate reward under policy action using the historical transition
            # (simplified: assume same reward if same action, slight bonus otherwise)
            if policy_action == actual_action:
                policy_reward_estimate += discount * step_reward
            else:
                # Conservative estimate: assume policy action gets similar reward
                # Real OPE would use a learned dynamics model here
                policy_reward_estimate += discount * step_reward * 0.9

            discount *= gamma

        improvement = policy_reward_estimate - actual_reward
        results.append({
            "actual_reward": actual_reward,
            "policy_reward_estimate": policy_reward_estimate,
            "improvement": improvement,
        })

    # Aggregate results
    improvements = [r["improvement"] for r in results]
    avg_improvement = float(np.mean(improvements))
    std_improvement = float(np.std(improvements))

    # Bootstrap confidence interval (95%)
    n_bootstrap = 1000
    bootstrap_means = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(improvements, size=len(improvements), replace=True)
        bootstrap_means.append(np.mean(sample))
    ci_lower = float(np.percentile(bootstrap_means, 2.5))
    ci_upper = float(np.percentile(bootstrap_means, 97.5))

    # Pass criteria: average improvement > 0 AND lower CI bound > 0
    passes = avg_improvement > 0 and ci_lower > 0

    evaluation_result = {
        "episodes_evaluated": len(results),
        "avg_improvement": round(avg_improvement, 4),
        "std_improvement": round(std_improvement, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "passes_threshold": passes,
        "recommendation": "DEPLOY" if passes else "DO_NOT_DEPLOY",
    }

    logger.info("Offline evaluation complete: %s", json.dumps(evaluation_result))
    return evaluation_result
```

---

## Step 5: Deploy as Decision Support with Constraint Checking

*The pseudocode calls this `generate_recommendation(hospital_id)`. The trained policy produces ranked recommendations that a human bed coordinator reviews. Every recommendation passes through a hard constraint checker before being shown.*

```python
# In production, the model artifact is loaded from SageMaker Model Registry.
# For this example, we'll assume the policy object is available.

sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb_client = boto3.client("dynamodb", config=BOTO3_RETRY_CONFIG)


def generate_recommendation(hospital_id: str, policy: PolicyNetwork) -> dict:
    """
    Generate resource allocation recommendations for the current hospital state.

    This is the inference path: called every 15-30 minutes by a scheduled
    Lambda or triggered by significant state changes (e.g., new ED boarder).

    Args:
        hospital_id: facility identifier
        policy: trained policy network (in production, loaded from model registry)

    Returns:
        Recommendation payload for the capacity dashboard
    """
    timestamp = time.time()

    # Build current state
    state = build_state_vector(hospital_id, timestamp)

    # Get action probabilities from policy
    action_probs = policy.forward(state)

    # Build feasibility mask from current constraints
    # In production, this calls the constraint checker with real hospital state
    sim = HospitalSimulator()  # temporary, just for constraint checking structure
    feasible_mask = np.ones(NUM_ACTIONS)
    # (In production, you'd check actual constraints against real state)

    # Mask and get top-K recommendations
    masked_probs = action_probs * feasible_mask
    if masked_probs.sum() > 0:
        masked_probs = masked_probs / masked_probs.sum()

    # Get top 3 actions
    top_k = 3
    top_indices = np.argsort(masked_probs)[::-1][:top_k]

    recommendations = []
    for idx in top_indices:
        action_name = ACTION_SPACE[idx]
        confidence = float(masked_probs[idx])

        if confidence < 0.05:
            continue  # skip very low-confidence actions

        recommendations.append({
            "action": action_name,
            "action_description": _describe_action(action_name),
            "confidence": round(confidence, 3),
            "explanation": _generate_explanation(action_name, state),
        })

    # Build the full recommendation payload
    recommendation_id = str(uuid.uuid4())
    payload = {
        "recommendation_id": recommendation_id,
        "hospital_id": hospital_id,
        "timestamp": int(timestamp),
        "recommendations": recommendations,
        "state_summary": _summarize_state(state),
        "constraint_status": "all_satisfied",
        "model_version": "v1.0.0-demo",
    }

    # Log for audit trail and future training
    _log_recommendation(payload)

    return payload


def _describe_action(action_name: str) -> str:
    """Human-readable description of each action."""
    descriptions = {
        "no_action": "No intervention needed at this time",
        "assign_ed_boarder_medsurg_a": "Move ED boarder to Med-Surg A",
        "assign_ed_boarder_medsurg_b": "Move ED boarder to Med-Surg B",
        "assign_ed_boarder_telemetry": "Move ED boarder to Telemetry",
        "assign_ed_boarder_stepdown": "Move ED boarder to Step-Down",
        "transfer_icu_to_stepdown": "Transfer stable ICU patient to Step-Down",
        "transfer_stepdown_to_medsurg": "Transfer step-down patient to Med-Surg floor",
        "float_nurse_to_icu": "Float nurse from lower-acuity unit to ICU",
        "float_nurse_to_ed": "Float nurse to ED for boarding patient care",
        "activate_overflow": "Activate overflow capacity section",
        "request_early_discharge_review": "Flag patients for expedited discharge review",
        "hold_or_bed_for_post_op": "Reserve bed for upcoming OR case completion",
    }
    return descriptions.get(action_name, action_name)


def _generate_explanation(action_name: str, state: np.ndarray) -> str:
    """
    Generate a brief explanation of why this action was recommended.

    In production, this would use SHAP values or attention weights from the
    policy network to identify which state features most influenced the
    recommendation. Here we use rule-based heuristics as a placeholder.
    """
    # Simplified: identify the most critical state features
    # (In production, use interpretability methods on the neural network)
    icu_occ = state[0] if len(state) > 0 else 0
    ed_boarders_feat = state[11] if len(state) > 11 else 0

    if "ed_boarder" in action_name:
        return (
            f"ED currently holding {int(ed_boarders_feat)} boarders. "
            f"Target unit has available capacity. Moving now prevents cascade "
            f"delays to incoming patients."
        )
    elif "transfer_icu" in action_name:
        return (
            f"ICU at {icu_occ:.0%} capacity with pending admissions. "
            f"Stepping down stable patient creates buffer for anticipated demand."
        )
    elif "float_nurse" in action_name:
        return (
            "Target unit approaching minimum staffing ratio. "
            "Source unit has surplus staff above minimum. "
            "Proactive float prevents violation before it occurs."
        )
    else:
        return "Recommended based on current state and predicted demand trajectory."


def _summarize_state(state: np.ndarray) -> dict:
    """Create a human-readable state summary for the dashboard."""
    return {
        "icu_occupancy": f"{state[0]:.0%}" if len(state) > 0 else "unknown",
        "stepdown_occupancy": f"{state[1]:.0%}" if len(state) > 1 else "unknown",
        "medsurg_occupancy": f"{(state[2] + state[3]) / 2:.0%}" if len(state) > 3 else "unknown",
        "ed_boarders": int(state[11]) if len(state) > 11 else 0,
        "or_cases_remaining": int(state[15]) if len(state) > 15 else 0,
    }


def _log_recommendation(payload: dict):
    """
    Write recommendation to DynamoDB for audit trail and feedback collection.

    Every recommendation is logged regardless of whether the human accepts it.
    Acceptance/rejection data feeds back into future training cycles.
    """
    table = dynamodb.Table("hospital-resource-recommendations")

    # Convert floats to Decimal for DynamoDB
    item = json.loads(json.dumps(payload), parse_float=Decimal)
    item["ttl"] = int(time.time()) + (90 * 24 * 3600)  # 90-day retention

    table.put_item(Item=item)
    logger.info("Logged recommendation %s", payload["recommendation_id"])
```

---

## Full Pipeline: End-to-End Training and Deployment

Here's how all the pieces come together. In production, this would be orchestrated by an AWS Step Functions workflow that runs weekly or monthly.

```python
def run_full_pipeline(hospital_id: str):
    """
    End-to-end pipeline: train policy, evaluate offline, deploy if passing.

    In production, each step is a separate SageMaker job orchestrated by
    Step Functions. This function shows the logical flow.
    """
    print("=" * 60)
    print("HOSPITAL RESOURCE ALLOCATION RL PIPELINE")
    print("=" * 60)

    # --- Step 1: Train policy in simulation ---
    print("\n[1/4] Training policy in hospital simulator...")
    print(f"      Episodes: {TRAINING_CONFIG['num_episodes']}")
    print(f"      Episode length: {TRAINING_CONFIG['episode_length_hours']} hours")
    print(f"      Decision interval: {TRAINING_CONFIG['decision_interval_minutes']} min")

    # In production: sagemaker.create_training_job() with custom RL container
    policy = train_policy_loop(num_episodes=100)  # reduced for demo
    print("      Training complete.")

    # --- Step 2: Evaluate against historical data ---
    print("\n[2/4] Evaluating policy against historical operations...")
    # In production: load real historical episodes from S3
    # For demo: generate synthetic evaluation data
    eval_result = {
        "episodes_evaluated": 30,
        "avg_improvement": 0.15,
        "ci_95_lower": 0.03,
        "ci_95_upper": 0.27,
        "passes_threshold": True,
        "recommendation": "DEPLOY",
    }
    print(f"      Episodes evaluated: {eval_result['episodes_evaluated']}")
    print(f"      Average improvement: {eval_result['avg_improvement']:.1%}")
    print(f"      95% CI: [{eval_result['ci_95_lower']:.1%}, {eval_result['ci_95_upper']:.1%}]")
    print(f"      Recommendation: {eval_result['recommendation']}")

    # --- Step 3: Register model (only if evaluation passes) ---
    if not eval_result["passes_threshold"]:
        print("\n[STOP] Policy did not pass offline evaluation. Not deploying.")
        print("       Review constraint satisfaction and reward shaping.")
        return

    print("\n[3/4] Registering model in SageMaker Model Registry...")
    # In production: sagemaker model registry with approval workflow
    model_version = f"v1.0.{int(time.time())}"
    print(f"      Registered as: {model_version}")

    # --- Step 4: Generate sample recommendation ---
    print("\n[4/4] Generating sample recommendation for current state...")
    recommendation = generate_recommendation(hospital_id, policy)

    print(f"\n      Recommendation ID: {recommendation['recommendation_id']}")
    print(f"      State summary: {json.dumps(recommendation['state_summary'], indent=2)}")
    print(f"      Top recommendations:")
    for i, rec in enumerate(recommendation.get("recommendations", []), 1):
        print(f"        {i}. {rec['action_description']} (confidence: {rec['confidence']:.1%})")
        print(f"           {rec['explanation']}")

    print("\n" + "=" * 60)
    print("Pipeline complete. Model ready for decision support deployment.")
    print("=" * 60)


if __name__ == "__main__":
    run_full_pipeline(hospital_id="hospital-demo-001")
```

---

## Gap to Production

This example shows the skeleton. Here's what you'd need for a real deployment:

**Simulation fidelity.** The simulator above uses basic Poisson arrivals and uniform distributions. A real simulator needs:
- Fitted arrival models from 2+ years of ADT data (time-of-day, day-of-week, seasonal patterns)
- Log-normal length-of-stay distributions stratified by diagnosis group
- Individual patient acuity trajectories (patients improve and deteriorate)
- OR schedule integration with realistic case durations
- Staff behavior modeling (response times, float preferences)
- Equipment maintenance and failure modes

**Proper RL framework.** The numpy policy network here doesn't actually learn (no backpropagation). Use SageMaker RL with RLlib, which provides:
- PPO with proper advantage estimation (GAE)
- Distributed rollout workers for parallel simulation
- GPU-accelerated policy updates
- Proper value function baseline
- Entropy bonus for exploration

**Off-policy evaluation.** The evaluation function above is extremely simplified. Real OPE requires:
- Fitted Q-Evaluation (FQE) for lower-variance estimates
- Doubly-robust estimators to balance bias and variance
- Multiple OPE methods cross-validated against each other
- Confidence intervals that account for distributional shift
- Sensitivity analysis to modeling assumptions

**Domain randomization.** During training, randomize simulator parameters (arrival rates, LOS, staffing levels) to make the policy robust to miscalibration. The sim-to-real gap is the biggest risk. If your simulator is wrong, your policy is optimized for the wrong world.

**Error handling and retries.** Every AWS API call needs proper exception handling with exponential backoff. Kinesis streams can have hot shards. DynamoDB can throttle during training data writes. SageMaker training jobs can fail from spot instance interruptions.

**Input validation.** State vectors from real hospital systems will have missing data, stale values, and impossible combinations. Validate ranges, check timestamps for staleness, and have fallback behavior when data quality is poor.

**Structured logging.** All recommendations, state observations, and human decisions need structured JSON logging for CloudWatch Logs Insights. Include correlation IDs that connect a recommendation to the state that generated it and the human decision that followed.

**IAM least privilege.** The inference Lambda should only have permissions for the specific DynamoDB table and model artifact. The training pipeline needs broader permissions but only during execution. Separate roles for training vs. inference.

**VPC configuration.** All components handling operational data (which contains PHI through room assignments and acuity levels) must run in private subnets. VPC endpoints for S3, DynamoDB, SageMaker, and Kinesis. No public internet access for data-plane traffic.

**KMS encryption.** Use customer-managed KMS keys for S3 training data, DynamoDB state tables, and model artifacts. Key policies should restrict access to the specific roles that need decryption.

**Monitoring and alerting.** CloudWatch alarms for:
- Recommendation latency exceeding SLA
- State data staleness (no updates in > 5 minutes)
- Model drift (recommendation distribution shifting unexpectedly)
- Constraint checker firing rate (if constraints are hit constantly, something is wrong)
- Human rejection rate (high rejection = policy misalignment)

**Human feedback loop.** Every recommendation must have an easy accept/reject/modify workflow in the dashboard. This data is gold for retraining. Track what humans change and why. Feed accepted-action distributions back as a behavioral cloning signal to keep the policy aligned with operational preferences.

**A/B evaluation protocol.** Before system-wide deployment, run a controlled pilot:
- Randomize by time block (recommendations shown vs. hidden on alternating shifts)
- Or randomize by unit (some units get recommendations, others don't)
- Measure the same operational KPIs used in offline evaluation
- Run for 4-8 weeks minimum to capture weekly patterns
- Pre-register the evaluation metrics and success criteria

**Reward function governance.** The weights in `REWARD_WEIGHTS` are organizational policy decisions, not engineering parameters. Changes require approval from hospital operations leadership. Version-control the weights and log which weight configuration was used for each training run.

---

| [← 15.9: Python Example](chapter15.09-python-example) | [Chapter 15 Index](chapter15-preface) | |
