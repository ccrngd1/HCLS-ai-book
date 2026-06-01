# Recipe 15.1: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the RL-based alert threshold optimization from Recipe 15.1. It demonstrates the core concepts (environment definition, agent logic, reward shaping, safety constraints) in working Python. It is not production-ready. A real deployment requires EHR integration, clinical governance, months of offline validation, and infrastructure that this example intentionally skips. Think of it as a simulation sandbox for understanding how the pieces fit together, not something you'd connect to a live alerting system.

---

## Setup

You'll need a few packages:

```bash
pip install boto3 numpy
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `s3:GetObject`, `s3:PutObject`, `kinesis:PutRecord`, and `cloudwatch:PutMetricData`.

For the simulation portions of this example (the RL environment and training loop), you only need `numpy`. The AWS calls are in the deployment sections.

---

## Config and Constants

Before we get to the logic, here's the configuration that drives the entire system. These constants encode clinical priorities, safety bounds, and operational parameters. In a real deployment, these would live in a configuration service (DynamoDB, Parameter Store) so clinical leadership can adjust them without code changes.

```python
import numpy as np
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# =============================================================================
# REWARD CONFIGURATION
# These weights encode clinical priorities. The relative magnitudes matter:
# a missed event is penalized 5x more than a noisy alert, because the
# consequences of missing a real deterioration are far worse than annoying
# a nurse with one extra beep.
# =============================================================================

REWARD_CONFIG = {
    "action_taken": 1.0,       # Alert led to a clinical intervention: good signal
    "dismissed": -0.3,         # Alert dismissed within seconds: noise
    "acknowledged": 0.1,       # Acknowledged but no action: ambiguous, slight positive
    "missed_event": -5.0,      # Deterioration with no preceding alert: very bad
    "no_change_bonus": 0.01,   # Tiny reward for stability (discourages thrashing)
}

# =============================================================================
# SAFETY BOUNDS
# These are set by clinical leadership. The RL agent can optimize within
# these ranges but can NEVER exceed them. The max_daily_change prevents
# the agent from making large swings that confuse clinicians.
# =============================================================================

SAFETY_BOUNDS = {
    "heart_rate_high": {"min": 90, "max": 150, "max_daily_change": 5, "step_size": 1.0},
    "heart_rate_low": {"min": 40, "max": 60, "max_daily_change": 3, "step_size": 1.0},
    "spo2_low": {"min": 85, "max": 95, "max_daily_change": 2, "step_size": 1.0},
    "potassium_high": {"min": 5.0, "max": 6.5, "max_daily_change": 0.3, "step_size": 0.1},
    "systolic_bp_high": {"min": 140, "max": 200, "max_daily_change": 10, "step_size": 2.0},
}

# =============================================================================
# ENVIRONMENT PARAMETERS
# These control the simulation. In production, you wouldn't simulate;
# you'd observe real alert events and clinician responses.
# =============================================================================

ENVIRONMENT_CONFIG = {
    "response_window_seconds": 300,  # 5 minutes to respond before "dismissed"
    "state_aggregation_hours": 4,    # Aggregate over one half-shift
    "update_frequency_hours": 8,     # Update thresholds once per shift
    "rollback_threshold": 0.5,       # Rollback if action rate drops below this fraction of baseline
}

# =============================================================================
# AGENT HYPERPARAMETERS
# These control the learning algorithm. Start conservative (low learning rate,
# high epsilon) and tighten as you gain confidence in the policy.
# =============================================================================

AGENT_CONFIG = {
    "learning_rate": 0.01,       # How fast the agent updates its estimates
    "discount_factor": 0.95,     # How much future rewards matter vs. immediate
    "epsilon_start": 0.3,        # Initial exploration rate (30% random actions)
    "epsilon_end": 0.05,         # Final exploration rate (5% random actions)
    "epsilon_decay": 0.995,      # Multiply epsilon by this each episode
}
```

---

## Step 1: Define the Alert Environment

*The main recipe describes the MDP formulation: state, actions, rewards, transitions. This step implements that as a simulated environment the agent can learn from. In production, the "environment" is the real hospital. For development and offline training, we simulate it.*

```python
class AlertEnvironment:
    """
    Simulates a clinical alerting environment for one unit and one alert type.

    The environment models:
    - A patient population with varying acuity
    - Alert firing based on current thresholds
    - Clinician responses (action, dismiss, acknowledge) based on alert relevance
    - Occasional deterioration events that test whether alerts catch real problems

    This is a simplified simulation. Real alert patterns are messier, more
    correlated, and harder to model. But this captures the core dynamics:
    lower thresholds = more alerts = more noise but fewer missed events.
    Higher thresholds = fewer alerts = less noise but risk of missing things.
    """

    def __init__(self, alert_type: str, initial_threshold: float, seed: int = 42):
        self.alert_type = alert_type
        self.bounds = SAFETY_BOUNDS[alert_type]
        self.threshold = initial_threshold
        self.rng = np.random.default_rng(seed)

        # Track daily changes for rate limiting
        self.daily_changes = []
        self.current_day = 0

        # Simulation parameters (these model "reality")
        # The "true" optimal threshold where alerts are most informative.
        # The agent doesn't know this; it has to discover it through rewards.
        self._true_optimal = (self.bounds["min"] + self.bounds["max"]) / 2

        # Counters for metrics
        self.total_alerts = 0
        self.total_actions = 0
        self.total_dismissed = 0
        self.missed_events = 0
        self.steps = 0

    def get_state(self) -> np.ndarray:
        """
        Return the current state as a feature vector.

        Maps to the pseudocode's aggregate_state() function. In production,
        this would query DynamoDB for recent alert statistics. Here we
        compute it from the simulation's internal counters.
        """
        # Normalize features to [0, 1] range for the agent
        threshold_normalized = (self.threshold - self.bounds["min"]) / (
            self.bounds["max"] - self.bounds["min"]
        )

        # Simulated context features
        alerts_per_hour = self._simulate_alert_rate()
        action_rate = self.total_actions / max(self.total_alerts, 1)
        dismiss_rate = self.total_dismissed / max(self.total_alerts, 1)
        hour_of_day = (self.steps % 24) / 24.0
        acuity = self.rng.uniform(0.3, 0.8)  # simulated average patient acuity

        state = np.array([
            threshold_normalized,
            min(alerts_per_hour / 20.0, 1.0),  # cap at 20/hr for normalization
            action_rate,
            dismiss_rate,
            hour_of_day,
            acuity,
        ], dtype=np.float32)

        return state

    def step(self, action: int) -> tuple:
        """
        Take an action (adjust threshold) and observe the result.

        Actions:
            0 = decrease threshold by one step (more sensitive, more alerts)
            1 = no change
            2 = increase threshold by one step (less sensitive, fewer alerts)

        Returns:
            (next_state, reward, done, info)
        """
        self.steps += 1
        step_size = self.bounds["step_size"]

        # Map action index to threshold delta
        delta_map = {0: -step_size, 1: 0.0, 2: step_size}
        delta = delta_map[action]

        # Apply safety constraints (mirrors pseudocode Step 6)
        new_threshold = self._apply_safely(delta)
        self.threshold = new_threshold

        # Simulate what happens at this threshold for one time period
        reward, info = self._simulate_period()

        next_state = self.get_state()
        done = self.steps >= 1000  # episode length

        return next_state, reward, done, info

    def _apply_safely(self, delta: float) -> float:
        """
        Apply threshold change with safety constraints.
        Mirrors the apply_threshold_safely() pseudocode from the main recipe.
        """
        proposed = self.threshold + delta

        # Enforce absolute bounds
        proposed = max(proposed, self.bounds["min"])
        proposed = min(proposed, self.bounds["max"])

        # Enforce daily rate limit
        today = self.steps // 24
        if today != self.current_day:
            self.daily_changes = []
            self.current_day = today

        total_daily = sum(abs(c) for c in self.daily_changes) + abs(delta)
        if total_daily > self.bounds["max_daily_change"]:
            # Rate limit exceeded; no change
            return self.threshold

        self.daily_changes.append(delta)
        return proposed

    def _simulate_alert_rate(self) -> float:
        """Simulate alerts per hour based on current threshold."""
        # Lower threshold = more alerts (exponential relationship)
        distance_from_min = self.threshold - self.bounds["min"]
        range_size = self.bounds["max"] - self.bounds["min"]
        # At minimum threshold: ~15 alerts/hr. At maximum: ~1 alert/hr.
        rate = 15.0 * np.exp(-3.0 * distance_from_min / range_size)
        return max(rate, 0.5)

    def _simulate_period(self) -> tuple:
        """
        Simulate one time period (e.g., one shift) and compute reward.

        Models the probability of alerts being actionable vs. noise,
        and the probability of missed events at the current threshold.
        """
        alerts_per_hour = self._simulate_alert_rate()
        num_alerts = int(self.rng.poisson(alerts_per_hour * ENVIRONMENT_CONFIG["update_frequency_hours"]))

        # Probability that an alert is actionable depends on how close
        # the threshold is to the "true optimal." Too low = mostly noise.
        # Too high = you miss things but what fires is more likely real.
        distance_from_optimal = abs(self.threshold - self._true_optimal)
        range_size = self.bounds["max"] - self.bounds["min"]
        action_probability = 0.4 * np.exp(-2.0 * distance_from_optimal / range_size) + 0.05

        # Simulate clinician responses for each alert
        period_reward = 0.0
        actions_taken = 0
        dismissed = 0

        for _ in range(num_alerts):
            if self.rng.random() < action_probability:
                # Clinician took action: alert was useful
                period_reward += REWARD_CONFIG["action_taken"]
                actions_taken += 1
            elif self.rng.random() < 0.1:
                # Acknowledged but no action
                period_reward += REWARD_CONFIG["acknowledged"]
            else:
                # Dismissed: noise
                period_reward += REWARD_CONFIG["dismissed"]
                dismissed += 1

        # Simulate missed events: higher threshold = higher miss probability
        threshold_normalized = (self.threshold - self.bounds["min"]) / range_size
        miss_probability = 0.01 * (threshold_normalized ** 2)  # quadratic: risk grows fast at high thresholds
        if self.rng.random() < miss_probability:
            period_reward += REWARD_CONFIG["missed_event"]
            self.missed_events += 1

        # Stability bonus for no-change actions
        if num_alerts == 0:
            period_reward += REWARD_CONFIG["no_change_bonus"]

        # Update counters
        self.total_alerts += num_alerts
        self.total_actions += actions_taken
        self.total_dismissed += dismissed

        info = {
            "alerts": num_alerts,
            "actions_taken": actions_taken,
            "dismissed": dismissed,
            "threshold": self.threshold,
            "action_rate": actions_taken / max(num_alerts, 1),
        }

        return period_reward, info
```

---

## Step 2: Implement the RL Agent

*The main recipe discusses contextual bandits and epsilon-greedy exploration. This implements a simple Q-learning agent with epsilon-greedy exploration and safety-aware action selection. For most alert threshold problems, this is sufficient. You don't need deep RL or policy gradients here.*

```python
class ThresholdAgent:
    """
    A tabular Q-learning agent for threshold optimization.

    Why Q-learning and not something fancier? Because the action space is tiny
    (3 actions: up, down, hold), the state can be discretized reasonably, and
    interpretability matters in healthcare. A clinician can look at the Q-table
    and understand why the agent chose a particular action. Try explaining a
    64-layer neural network policy to a chief medical officer.

    For larger state spaces or continuous actions, you'd upgrade to DQN or
    a policy gradient method. But start simple. You can always add complexity
    later if the simple version doesn't converge.
    """

    def __init__(self, state_bins: int = 10, n_actions: int = 3):
        self.n_actions = n_actions
        self.state_bins = state_bins
        self.lr = AGENT_CONFIG["learning_rate"]
        self.gamma = AGENT_CONFIG["discount_factor"]
        self.epsilon = AGENT_CONFIG["epsilon_start"]
        self.epsilon_end = AGENT_CONFIG["epsilon_end"]
        self.epsilon_decay = AGENT_CONFIG["epsilon_decay"]

        # Q-table: maps discretized state to action values.
        # We discretize each state dimension into bins, then use the
        # tuple of bin indices as the state key.
        # Initialize optimistically (small positive values) to encourage exploration.
        self.q_table = {}

    def _discretize_state(self, state: np.ndarray) -> tuple:
        """
        Convert continuous state vector to discrete bin indices.

        Each dimension is clipped to [0, 1] and mapped to one of state_bins buckets.
        The resulting tuple is hashable and serves as the Q-table key.
        """
        clipped = np.clip(state, 0.0, 1.0)
        bins = (clipped * (self.state_bins - 1)).astype(int)
        return tuple(bins)

    def _get_q_values(self, state_key: tuple) -> np.ndarray:
        """Get Q-values for a state, initializing if unseen."""
        if state_key not in self.q_table:
            # Optimistic initialization: start with small positive values
            # so the agent is encouraged to try all actions at least once.
            self.q_table[state_key] = np.full(self.n_actions, 0.1)
        return self.q_table[state_key]

    def choose_action(self, state: np.ndarray) -> int:
        """
        Select an action using epsilon-greedy exploration.

        With probability epsilon: choose a random action (explore).
        With probability (1 - epsilon): choose the best-known action (exploit).

        The epsilon decays over time, so the agent explores less as it
        becomes more confident in its learned values.
        """
        state_key = self._discretize_state(state)
        q_values = self._get_q_values(state_key)

        if np.random.random() < self.epsilon:
            # Explore: random action
            return np.random.randint(self.n_actions)
        else:
            # Exploit: best known action (break ties randomly)
            max_q = np.max(q_values)
            best_actions = np.where(q_values == max_q)[0]
            return np.random.choice(best_actions)

    def update(self, state: np.ndarray, action: int, reward: float, next_state: np.ndarray, done: bool):
        """
        Update Q-values using the standard Q-learning update rule.

        Q(s, a) <- Q(s, a) + lr * (reward + gamma * max(Q(s', a')) - Q(s, a))

        This is the core learning step. The agent adjusts its estimate of
        how good action 'a' is in state 's' based on the reward it received
        and its estimate of future value from the next state.
        """
        state_key = self._discretize_state(state)
        next_state_key = self._discretize_state(next_state)

        q_values = self._get_q_values(state_key)
        next_q_values = self._get_q_values(next_state_key)

        # The target: immediate reward + discounted future value
        if done:
            target = reward
        else:
            target = reward + self.gamma * np.max(next_q_values)

        # Update toward the target
        q_values[action] += self.lr * (target - q_values[action])

        # Decay exploration rate
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

    def get_policy_summary(self) -> dict:
        """Return a human-readable summary of what the agent has learned."""
        return {
            "states_visited": len(self.q_table),
            "epsilon": round(self.epsilon, 4),
            "sample_preferences": self._sample_preferences(),
        }

    def _sample_preferences(self) -> list:
        """Show the agent's preferred action for a few representative states."""
        action_names = ["decrease (more sensitive)", "hold", "increase (less sensitive)"]
        samples = []
        for state_key, q_values in list(self.q_table.items())[:5]:
            best_action = int(np.argmax(q_values))
            samples.append({
                "state_bins": state_key,
                "preferred_action": action_names[best_action],
                "q_values": [round(float(q), 3) for q in q_values],
            })
        return samples
```

---

## Step 3: Training Loop (Offline Learning)

*The main recipe emphasizes starting with offline learning: train on historical data before touching the live system. This step runs the agent through simulated episodes to learn a policy. In production, you'd replace the simulated environment with replay of historical alert data.*

```python
def train_agent(
    alert_type: str = "heart_rate_high",
    initial_threshold: float = 100.0,
    n_episodes: int = 50,
    seed: int = 42,
) -> tuple:
    """
    Train the RL agent on simulated alert data.

    In production, this function would:
    1. Load historical alert logs from S3
    2. Replay them through the environment (offline RL)
    3. Save the trained policy to S3 for deployment via SageMaker

    Here, we simulate the environment to demonstrate the learning dynamics.

    Returns:
        (agent, training_history) - the trained agent and per-episode metrics
    """
    env = AlertEnvironment(alert_type, initial_threshold, seed=seed)
    agent = ThresholdAgent(state_bins=10, n_actions=3)

    history = []

    for episode in range(n_episodes):
        # Reset environment for each episode
        env = AlertEnvironment(alert_type, initial_threshold, seed=seed + episode)
        state = env.get_state()
        episode_reward = 0.0
        episode_steps = 0

        done = False
        while not done:
            action = agent.choose_action(state)
            next_state, reward, done, info = env.step(action)
            agent.update(state, action, reward, next_state, done)

            state = next_state
            episode_reward += reward
            episode_steps += 1

            # Cap episode length for training efficiency
            if episode_steps >= 100:
                break

        # Record episode metrics
        episode_metrics = {
            "episode": episode,
            "total_reward": round(episode_reward, 2),
            "final_threshold": round(env.threshold, 1),
            "total_alerts": env.total_alerts,
            "action_rate": round(env.total_actions / max(env.total_alerts, 1), 3),
            "missed_events": env.missed_events,
            "epsilon": round(agent.epsilon, 4),
        }
        history.append(episode_metrics)

        if episode % 10 == 0:
            logger.info(
                "Episode %d: reward=%.1f, threshold=%.1f, action_rate=%.3f, missed=%d",
                episode, episode_reward, env.threshold,
                episode_metrics["action_rate"], env.missed_events,
            )

    return agent, history
```

---

## Step 4: Safety Constraint Enforcement

*The main recipe's Step 6 (apply_threshold_safely) is the critical safety layer. This step implements it as a standalone module that sits between the agent's recommendations and the live system. In production, this would write to DynamoDB with conditional expressions that enforce bounds at the storage layer.*

```python
import boto3
from botocore.config import Config

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

THRESHOLD_TABLE = "alert-thresholds"
AUDIT_TABLE = "threshold-audit-log"


def apply_threshold_update(
    alert_type: str,
    unit: str,
    current_threshold: float,
    proposed_delta: float,
    confidence: float,
    daily_changes_so_far: float,
) -> dict:
    """
    Apply a threshold change with full safety constraint enforcement.

    This is the gatekeeper. No matter what the RL agent recommends, this
    function ensures:
    1. The new threshold stays within clinical safety bounds
    2. Daily rate limits are respected
    3. Every change is logged for audit
    4. Rollback information is preserved

    Returns a dict with the outcome: applied, clamped, or rejected.
    """
    bounds = SAFETY_BOUNDS.get(alert_type)
    if bounds is None:
        return {"status": "rejected", "reason": f"Unknown alert type: {alert_type}"}

    proposed_new = current_threshold + proposed_delta

    # Constraint 1: Absolute bounds
    clamped = False
    if proposed_new > bounds["max"]:
        proposed_new = bounds["max"]
        clamped = True
    if proposed_new < bounds["min"]:
        proposed_new = bounds["min"]
        clamped = True

    # Constraint 2: Daily rate limit
    if daily_changes_so_far + abs(proposed_delta) > bounds["max_daily_change"]:
        return {
            "status": "rejected",
            "reason": "Daily rate limit exceeded",
            "daily_budget_remaining": bounds["max_daily_change"] - daily_changes_so_far,
        }

    # Constraint 3: Minimum confidence (don't act on uncertain recommendations)
    if confidence < 0.3:
        return {
            "status": "rejected",
            "reason": f"Agent confidence too low: {confidence:.2f}",
        }

    actual_delta = proposed_new - current_threshold

    # If no actual change after constraints, skip the write
    if abs(actual_delta) < 0.001:
        return {"status": "no_change", "threshold": current_threshold}

    # Build the audit record
    audit_record = {
        "alert_type": alert_type,
        "unit": unit,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "old_threshold": Decimal(str(round(current_threshold, 2))),
        "new_threshold": Decimal(str(round(proposed_new, 2))),
        "proposed_delta": Decimal(str(round(proposed_delta, 2))),
        "actual_delta": Decimal(str(round(actual_delta, 2))),
        "clamped": clamped,
        "confidence": Decimal(str(round(confidence, 3))),
        "change_source": "rl_agent",
    }

    return {
        "status": "applied" if not clamped else "clamped",
        "old_threshold": current_threshold,
        "new_threshold": proposed_new,
        "actual_delta": actual_delta,
        "audit_record": audit_record,
    }


def write_threshold_to_dynamodb(alert_type: str, unit: str, new_threshold: float, audit_record: dict):
    """
    Persist the new threshold and audit trail to DynamoDB.

    Uses conditional writes to prevent race conditions: the update only
    succeeds if the current threshold in the database matches what we
    expect. If another process changed it in the meantime, we fail safely
    and retry on the next cycle.
    """
    table = dynamodb.Table(THRESHOLD_TABLE)

    # Conditional write: only update if the stored threshold matches our expectation.
    # This prevents two concurrent Lambda invocations from both applying changes.
    try:
        table.update_item(
            Key={"alert_type": alert_type, "unit": unit},
            UpdateExpression="SET threshold_value = :new_val, last_updated = :ts",
            ConditionExpression="threshold_value = :expected",
            ExpressionAttributeValues={
                ":new_val": Decimal(str(round(new_threshold, 2))),
                ":expected": audit_record["old_threshold"],
                ":ts": audit_record["timestamp"],
            },
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning(
            "Conditional write failed for %s/%s. Threshold was modified externally.",
            alert_type, unit,
        )
        return False

    # Write audit log (separate table for compliance)
    audit_table = dynamodb.Table(AUDIT_TABLE)
    audit_record["pk"] = f"{alert_type}#{unit}"
    audit_record["sk"] = audit_record["timestamp"]
    audit_table.put_item(Item=audit_record)

    return True
```

---

## Step 5: Monitoring and Rollback

*The main recipe emphasizes CloudWatch monitoring with automatic rollback. This step implements the monitoring logic that detects degradation and triggers a revert to the previous threshold.*

```python
cloudwatch = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)

METRIC_NAMESPACE = "HealthcareAI/AlertOptimization"


def emit_metrics(alert_type: str, unit: str, metrics: dict):
    """
    Publish threshold optimization metrics to CloudWatch.

    These metrics drive the rollback alarms. If action_rate drops or
    missed_events spike, CloudWatch alarms trigger automatic rollback.
    """
    timestamp = datetime.datetime.now(timezone.utc)
    dimensions = [
        {"Name": "AlertType", "Value": alert_type},
        {"Name": "Unit", "Value": unit},
    ]

    metric_data = [
        {
            "MetricName": "ActionRate",
            "Value": metrics.get("action_rate", 0.0),
            "Unit": "None",
            "Timestamp": timestamp,
            "Dimensions": dimensions,
        },
        {
            "MetricName": "AlertsPerHour",
            "Value": metrics.get("alerts_per_hour", 0.0),
            "Unit": "Count",
            "Timestamp": timestamp,
            "Dimensions": dimensions,
        },
        {
            "MetricName": "MissedEvents",
            "Value": metrics.get("missed_events", 0),
            "Unit": "Count",
            "Timestamp": timestamp,
            "Dimensions": dimensions,
        },
        {
            "MetricName": "CurrentThreshold",
            "Value": metrics.get("threshold", 0.0),
            "Unit": "None",
            "Timestamp": timestamp,
            "Dimensions": dimensions,
        },
    ]

    cloudwatch.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=metric_data)


def check_rollback_needed(alert_type: str, unit: str, current_action_rate: float, baseline_action_rate: float) -> bool:
    """
    Determine if the current threshold should be rolled back.

    Rollback triggers if:
    1. Action rate drops below 50% of baseline (thresholds too permissive, missing things)
    2. Any missed event occurs (immediate rollback for safety)

    In production, this logic lives in a CloudWatch Alarm that triggers
    a Lambda function to revert the threshold. Here we show the decision logic.
    """
    rollback_threshold = ENVIRONMENT_CONFIG["rollback_threshold"]

    if baseline_action_rate > 0 and current_action_rate < baseline_action_rate * rollback_threshold:
        logger.warning(
            "ROLLBACK TRIGGERED for %s/%s: action_rate %.3f < %.3f (baseline * %.1f)",
            alert_type, unit, current_action_rate,
            baseline_action_rate * rollback_threshold, rollback_threshold,
        )
        return True

    return False


def rollback_threshold(alert_type: str, unit: str, previous_threshold: float):
    """
    Revert to the previous known-good threshold.

    This is the nuclear option. When triggered, it:
    1. Writes the old threshold back to DynamoDB
    2. Logs the rollback event for audit
    3. Emits a CloudWatch metric so dashboards show the revert
    4. (In production) pages the on-call engineer
    """
    table = dynamodb.Table(THRESHOLD_TABLE)

    table.update_item(
        Key={"alert_type": alert_type, "unit": unit},
        UpdateExpression="SET threshold_value = :val, last_updated = :ts, rollback = :rb",
        ExpressionAttributeValues={
            ":val": Decimal(str(round(previous_threshold, 2))),
            ":ts": datetime.datetime.now(timezone.utc).isoformat(),
            ":rb": True,
        },
    )

    logger.info("Rolled back %s/%s to threshold %.2f", alert_type, unit, previous_threshold)
```

---

## Putting It All Together

Here's the full pipeline: train an agent, evaluate its learned policy, and show how it would integrate with the AWS infrastructure for deployment.

```python
def run_full_demo():
    """
    Demonstrate the complete alert threshold optimization pipeline.

    1. Train an agent on simulated data
    2. Evaluate the learned policy
    3. Show how a threshold update would flow through safety constraints
    4. Demonstrate the monitoring and rollback logic
    """
    print("=" * 70)
    print("ALERT THRESHOLD OPTIMIZATION - RL TRAINING DEMO")
    print("=" * 70)

    # --- Phase 1: Train the agent ---
    print("\n--- Phase 1: Training ---")
    print("Training agent on simulated ICU heart rate alert data...")
    print("(In production, this trains on 6+ months of historical alert logs from S3)")

    agent, history = train_agent(
        alert_type="heart_rate_high",
        initial_threshold=100.0,
        n_episodes=50,
        seed=42,
    )

    print(f"\nTraining complete.")
    print(f"  Episodes: {len(history)}")
    print(f"  Final epsilon (exploration rate): {agent.epsilon:.4f}")
    print(f"  States visited: {len(agent.q_table)}")

    # Show learning progress
    early_reward = np.mean([h["total_reward"] for h in history[:10]])
    late_reward = np.mean([h["total_reward"] for h in history[-10:]])
    print(f"  Avg reward (first 10 episodes): {early_reward:.1f}")
    print(f"  Avg reward (last 10 episodes):  {late_reward:.1f}")

    # --- Phase 2: Evaluate learned policy ---
    print("\n--- Phase 2: Evaluation ---")
    env = AlertEnvironment("heart_rate_high", 100.0, seed=999)
    state = env.get_state()

    # Run one evaluation episode with no exploration (epsilon = 0)
    original_epsilon = agent.epsilon
    agent.epsilon = 0.0  # pure exploitation for evaluation

    eval_rewards = 0.0
    for _ in range(100):
        action = agent.choose_action(state)
        state, reward, done, info = env.step(action)
        eval_rewards += reward
        if done:
            break

    agent.epsilon = original_epsilon  # restore

    print(f"  Evaluation reward: {eval_rewards:.1f}")
    print(f"  Final threshold: {env.threshold:.1f} (started at 100.0)")
    print(f"  Total alerts: {env.total_alerts}")
    print(f"  Action rate: {env.total_actions / max(env.total_alerts, 1):.3f}")
    print(f"  Missed events: {env.missed_events}")

    # --- Phase 3: Safety constraint demo ---
    print("\n--- Phase 3: Safety Constraints ---")
    print("Demonstrating safety layer on proposed threshold changes...")

    # Normal update (should apply)
    result = apply_threshold_update(
        alert_type="heart_rate_high",
        unit="ICU-3A",
        current_threshold=105.0,
        proposed_delta=2.0,
        confidence=0.85,
        daily_changes_so_far=1.0,
    )
    print(f"\n  Normal update (+2 bpm): {result['status']}")
    if result["status"] in ("applied", "clamped"):
        print(f"    {result['old_threshold']} -> {result['new_threshold']}")

    # Update that exceeds daily limit (should reject)
    result = apply_threshold_update(
        alert_type="heart_rate_high",
        unit="ICU-3A",
        current_threshold=105.0,
        proposed_delta=3.0,
        confidence=0.85,
        daily_changes_so_far=4.0,
    )
    print(f"\n  Exceeds daily limit (+3, already changed 4 today): {result['status']}")
    print(f"    Reason: {result.get('reason', 'n/a')}")

    # Update that would exceed safety ceiling (should clamp)
    result = apply_threshold_update(
        alert_type="heart_rate_high",
        unit="ICU-3A",
        current_threshold=148.0,
        proposed_delta=5.0,
        confidence=0.9,
        daily_changes_so_far=0.0,
    )
    print(f"\n  Exceeds ceiling (148 + 5 > max 150): {result['status']}")
    if result["status"] == "clamped":
        print(f"    Clamped to: {result['new_threshold']}")

    # Low confidence (should reject)
    result = apply_threshold_update(
        alert_type="heart_rate_high",
        unit="ICU-3A",
        current_threshold=105.0,
        proposed_delta=1.0,
        confidence=0.15,
        daily_changes_so_far=0.0,
    )
    print(f"\n  Low confidence (0.15): {result['status']}")
    print(f"    Reason: {result.get('reason', 'n/a')}")

    # --- Phase 4: Rollback logic ---
    print("\n--- Phase 4: Rollback Detection ---")
    baseline_action_rate = 0.20

    # Good state: no rollback needed
    needs_rollback = check_rollback_needed("heart_rate_high", "ICU-3A", 0.18, baseline_action_rate)
    print(f"  Action rate 0.18 vs baseline 0.20: rollback={needs_rollback}")

    # Bad state: action rate collapsed
    needs_rollback = check_rollback_needed("heart_rate_high", "ICU-3A", 0.05, baseline_action_rate)
    print(f"  Action rate 0.05 vs baseline 0.20: rollback={needs_rollback}")

    print("\n" + "=" * 70)
    print("Demo complete. See the main recipe for full architectural context.")
    print("=" * 70)


if __name__ == "__main__":
    run_full_demo()
```

---

## The Gap Between This and Production

This example demonstrates the RL concepts and safety patterns. Here's what separates it from something you'd deploy in a hospital:

**EHR integration.** The simulated environment is a toy. Real alert data comes from HL7/FHIR feeds, EHR audit logs, and clinical event streams. Extracting "clinician took action within 5 minutes of alert" from an EHR database is a data engineering project in itself. Most of the implementation timeline is here, not in the RL algorithm.

**Offline RL from historical data.** This example trains online (the agent interacts with a simulation). Production starts with offline RL: you replay 6-12 months of historical alert/response data and learn a policy without touching the live system. Offline RL has its own challenges (distribution shift, extrapolation error) that require techniques like Conservative Q-Learning (CQL) or batch-constrained methods.

**Model serving infrastructure.** The trained policy needs to be deployed as a SageMaker endpoint (or equivalent) that the threshold-update Lambda can call. Model versioning, A/B testing between policy versions, and canary deployments all matter. You don't just pickle the Q-table and call it done.

**Feature engineering.** The 6-dimensional state vector here is a simplification. A production state includes dozens of features: per-alert-type statistics, patient census data, staffing ratios, time since last threshold change, recent missed events, seasonal patterns, and more. Feature engineering is where domain expertise meets ML engineering.

**Reward function validation.** The reward weights in this example are made up. In production, you'd work with clinical leadership to calibrate them. How much worse is a missed event than 100 noisy alerts? That's a clinical judgment call, not an engineering decision. And you'd validate the reward function against historical outcomes before trusting it.

**Multi-unit, multi-alert coordination.** This example optimizes one alert type on one unit. A hospital has dozens of units and dozens of alert types. Some interact (raising the heart rate threshold might increase reliance on SpO2 alerts). A production system either trains independent agents per unit/type (simpler, ignores interactions) or uses a multi-agent approach (complex, captures interactions).

**Clinician feedback loop.** Beyond automated response tracking, production systems include a mechanism for clinicians to explicitly flag "this alert was useful" or "this alert was noise." That direct feedback is gold for reward shaping but requires UX work in the alerting interface.

**Audit and explainability.** Every threshold change needs a human-readable explanation: "Threshold raised from 105 to 107 because action rate was 0.08 (below target) and no missed events in 14 days." The audit trail in this example captures the numbers but not the narrative. Regulatory and clinical governance require both.

**Testing.** This example has no tests. A production system needs unit tests for the safety constraint logic (the most critical code path), integration tests against a simulated EHR feed, and backtesting infrastructure that replays historical periods to validate that the learned policy would have performed well.

**Gradual rollout.** You don't flip the switch for the whole hospital at once. Start with one alert type on one unit. Run in "shadow mode" (compute recommendations but don't apply them) for weeks. Compare shadow recommendations against actual outcomes. Then enable with tight safety bounds. Then gradually relax bounds as confidence grows. This takes months.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 15.1](chapter15.01-alert-threshold-optimization.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
