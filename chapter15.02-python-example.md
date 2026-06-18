# Recipe 15.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the contextual bandit concepts from Recipe 15.2. It shows one way you could translate notification timing optimization into working Python. It is not production-ready. The bandit algorithm here is a basic LinUCB implementation for educational purposes. In production, you'd use Amazon Personalize (which handles the algorithm, exploration, and scaling for you) rather than rolling your own. Think of this as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a patient engagement platform on Monday morning.

---

## Setup

You'll need the AWS SDK for Python and numpy for the linear algebra in LinUCB:

```bash
pip install boto3 numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem` (patient context store)
- `sqs:ReceiveMessage`, `sqs:DeleteMessage` (message queue)
- `scheduler:CreateSchedule`, `scheduler:DeleteSchedule` (EventBridge Scheduler)
- `mobiletargeting:SendMessages` (Pinpoint delivery)
- `kinesis:PutRecord` (engagement event stream)

---

## Config and Constants

Before we get to the logic, here's the configuration that drives the system. Time slots, safety constraints, reward values, and feature dimensions all live here so they're easy to find and tune.

```python
import datetime
from datetime import timezone
from decimal import Decimal

# TIME_SLOTS: The discrete set of 30-minute windows the agent can choose from.
# We only consider 7am-9pm (patient's local time). That's 28 slots.
# Each slot is represented as minutes-from-midnight for easy math.
TIME_SLOTS = list(range(420, 1260, 30))  # 420 = 7:00am, 1230 = 8:30pm

# Human-readable labels for logging and debugging.
def slot_to_time_str(slot_minutes: int) -> str:
    """Convert minutes-from-midnight to 'HH:MM' string."""
    hours = slot_minutes // 60
    minutes = slot_minutes % 60
    return f"{hours:02d}:{minutes:02d}"

# REWARD_MAP: Maps engagement event types to numeric reward values.
# These drive the learning signal. The asymmetry is intentional:
# completed actions are the gold standard, opt-outs are catastrophic.
REWARD_MAP = {
    "action_completed": 1.0,   # patient refilled, scheduled, etc.
    "link_clicked": 0.5,       # meaningful engagement, no action
    "message_opened": 0.3,     # opened but didn't act
    "ignored": 0.0,            # no engagement within 48 hours (baseline)
    "unsubscribed": -0.5,      # lost the channel entirely
    "spam_reported": -1.0,     # worst case: regulatory risk
}

# SAFETY CONSTRAINTS
QUIET_HOURS_START = 21 * 60   # 9:00pm (in minutes from midnight)
QUIET_HOURS_END = 7 * 60      # 7:00am
MAX_DAILY_MESSAGES = 2         # hard cap per patient per day
MAX_WEEKLY_MESSAGES = 7        # hard cap per patient per week

# LINUCB PARAMETERS
# alpha controls exploration. Higher = more exploration.
# 0.25 is a reasonable starting point for notification timing.
LINUCB_ALPHA = 0.25

# Feature dimension: how many features describe the context.
# Patient features (6) + temporal features (4) + message features (3) = 13
FEATURE_DIM = 13

# Number of actions (time slots the agent can choose from).
NUM_ACTIONS = len(TIME_SLOTS)  # 28
```

---

## The LinUCB Agent

*The main recipe uses Amazon Personalize for the bandit model. Here we implement LinUCB from scratch so you can see what's happening inside. LinUCB models the expected reward for each action as a linear function of context features, and adds an exploration bonus proportional to uncertainty.*

```python
import numpy as np

class LinUCBAgent:
    """
    Linear Upper Confidence Bound agent for contextual bandits.

    For each action (time slot), maintains:
    - A matrix (A) that accumulates outer products of context features
    - A vector (b) that accumulates reward-weighted context features

    The estimated reward for action a given context x is:
        theta_a = A_a^{-1} * b_a
        predicted_reward = theta_a . x
        exploration_bonus = alpha * sqrt(x^T * A_a^{-1} * x)
        UCB = predicted_reward + exploration_bonus

    The agent picks the action with the highest UCB score.
    """

    def __init__(self, n_actions: int, n_features: int, alpha: float):
        """
        Initialize the agent with identity matrices and zero vectors.

        Args:
            n_actions: Number of possible actions (time slots).
            n_features: Dimension of the context feature vector.
            alpha: Exploration parameter. Higher = more exploration.
        """
        self.n_actions = n_actions
        self.n_features = n_features
        self.alpha = alpha

        # Per-action matrices. A starts as identity (regularization).
        # b starts as zeros (no reward signal yet).
        self.A = [np.identity(n_features) for _ in range(n_actions)]
        self.b = [np.zeros(n_features) for _ in range(n_actions)]

    def select_action(self, context: np.ndarray) -> tuple[int, float]:
        """
        Select the best action (time slot) given the current context.

        Returns:
            Tuple of (action_index, ucb_score) for the selected action.
        """
        ucb_scores = np.zeros(self.n_actions)

        for a in range(self.n_actions):
            # Solve for theta: the learned weight vector for this action.
            A_inv = np.linalg.inv(self.A[a])
            theta = A_inv @ self.b[a]

            # Predicted reward: how good we think this action is.
            predicted = context @ theta

            # Exploration bonus: how uncertain we are about this action.
            # High uncertainty = we haven't tried this action much = explore it.
            uncertainty = np.sqrt(context @ A_inv @ context)

            ucb_scores[a] = predicted + self.alpha * uncertainty

        # Pick the action with the highest UCB score.
        best_action = int(np.argmax(ucb_scores))
        return best_action, float(ucb_scores[best_action])

    def update(self, action: int, context: np.ndarray, reward: float):
        """
        Update the model after observing a reward for a (context, action) pair.

        This is where learning happens. Each observation tightens the estimate
        of how good this action is in similar contexts.

        Args:
            action: The action index that was taken.
            context: The context feature vector at decision time.
            reward: The observed reward (from REWARD_MAP).
        """
        # Update A: accumulate the outer product of the context.
        # This reduces uncertainty for this action in similar contexts.
        self.A[action] += np.outer(context, context)

        # Update b: accumulate the reward-weighted context.
        # This shifts the predicted reward for this action in similar contexts.
        self.b[action] += reward * context
```

---

## Step 1: Build Context Features

*The pseudocode calls this `get_patient_context(patient_id)`. Here we fetch patient data from DynamoDB and assemble the numeric feature vector that the bandit model expects.*

```python
import boto3
import logging
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

PATIENT_TABLE_NAME = "notification-patient-context"

def build_context_features(patient_record: dict, message: dict) -> np.ndarray:
    """
    Assemble the feature vector from patient data and message metadata.

    The feature vector has 13 dimensions:
    - [0] historical_open_rate (0.0 to 1.0)
    - [1] historical_action_rate (0.0 to 1.0)
    - [2] days_since_last_message (normalized: days / 30)
    - [3] messages_last_7d (normalized: count / MAX_WEEKLY_MESSAGES)
    - [4] fatigue_score (0.0 to 1.0)
    - [5] age_bucket_normalized (age_bucket / 10, so 0.0 to ~1.0)
    - [6] day_of_week (0=Mon to 6=Sun, normalized: / 6)
    - [7] is_weekend (0 or 1)
    - [8] is_holiday (0 or 1)
    - [9] hour_of_day_normalized (current hour / 23)
    - [10] message_type_refill (1 if refill reminder, else 0)
    - [11] message_type_appointment (1 if appointment reminder, else 0)
    - [12] message_type_education (1 if educational content, else 0)

    Args:
        patient_record: Dict from DynamoDB with patient engagement history.
        message: Dict with message metadata (type, channel, urgency).

    Returns:
        numpy array of shape (FEATURE_DIM,) with normalized features.
    """
    now = datetime.datetime.now(timezone.utc)

    # Patient features (from stored engagement history).
    open_rate = float(patient_record.get("open_rate_30d", 0.15))
    action_rate = float(patient_record.get("action_rate_30d", 0.05))
    days_since_last = float(patient_record.get("days_since_last_send", 7))
    msgs_last_7d = int(patient_record.get("recent_message_count", 0))
    fatigue = float(patient_record.get("fatigue_score", 0.0))
    age_bucket = int(patient_record.get("age_bucket", 5))

    # Temporal features (from current time).
    day_of_week = now.weekday()  # 0=Monday, 6=Sunday
    is_weekend = 1.0 if day_of_week >= 5 else 0.0
    is_holiday = 0.0  # In production, check a holiday calendar.
    hour_normalized = now.hour / 23.0

    # Message type features (one-hot encoding of the three main types).
    msg_type = message.get("type", "other")
    type_refill = 1.0 if msg_type == "refill_reminder" else 0.0
    type_appointment = 1.0 if msg_type == "appointment_reminder" else 0.0
    type_education = 1.0 if msg_type == "education" else 0.0

    features = np.array([
        open_rate,
        action_rate,
        min(days_since_last / 30.0, 1.0),       # cap at 1.0
        min(msgs_last_7d / MAX_WEEKLY_MESSAGES, 1.0),
        fatigue,
        age_bucket / 10.0,
        day_of_week / 6.0,
        is_weekend,
        is_holiday,
        hour_normalized,
        type_refill,
        type_appointment,
        type_education,
    ], dtype=np.float64)

    return features

def get_patient_context(patient_id: str) -> dict:
    """
    Fetch the patient's engagement context from DynamoDB.

    Returns a dict with engagement history fields, or defaults for new patients.
    """
    table = dynamodb.Table(PATIENT_TABLE_NAME)

    response = table.get_item(Key={"patient_id": patient_id})

    if "Item" not in response:
        # New patient. Return population-level defaults.
        # The model will use these until it learns this patient's patterns.
        logger.info("No history for patient %s, using defaults", patient_id)
        return {
            "patient_id": patient_id,
            "open_rate_30d": Decimal("0.15"),
            "action_rate_30d": Decimal("0.05"),
            "days_since_last_send": Decimal("7"),
            "recent_message_count": 0,
            "fatigue_score": Decimal("0.0"),
            "age_bucket": 5,
            "timezone": "America/New_York",
            "messages_today": 0,
        }

    return response["Item"]
```

---

## Step 2: Apply Safety Constraints

*The pseudocode applies constraints after the model's recommendation. Here we implement the hard safety rules that the model cannot violate: quiet hours, frequency caps, and deadline enforcement.*

```python
def is_in_quiet_hours(slot_minutes: int) -> bool:
    """
    Check if a time slot falls within quiet hours (9pm-7am).

    Args:
        slot_minutes: Time slot as minutes from midnight.

    Returns:
        True if the slot is in quiet hours and should not be used.
    """
    # Quiet hours wrap around midnight: 9pm (1260) to 7am (420).
    if slot_minutes >= QUIET_HOURS_START:
        return True
    if slot_minutes < QUIET_HOURS_END:
        return True
    return False

def apply_safety_constraints(
    ranked_actions: list[tuple[int, float]],
    patient_context: dict,
    message: dict,
) -> int:
    """
    Filter the model's ranked action list through safety constraints.

    Returns the highest-scoring action that passes all constraints.
    If no action passes, returns the first valid slot after quiet hours.

    Args:
        ranked_actions: List of (action_index, score) sorted by score descending.
        patient_context: Patient record with frequency counters.
        message: Message metadata including deadline.

    Returns:
        The action index (into TIME_SLOTS) of the selected safe slot.
    """
    messages_today = int(patient_context.get("messages_today", 0))

    # If frequency cap is already hit, we can't send today at all.
    # Return the first valid slot tomorrow (7am = slot index 0).
    if messages_today >= MAX_DAILY_MESSAGES:
        logger.info("Frequency cap hit for patient. Deferring to tomorrow.")
        return 0  # First slot (7:00am) as a placeholder for "tomorrow"

    # Walk through ranked actions and find the first one that passes all constraints.
    for action_idx, score in ranked_actions:
        slot_minutes = TIME_SLOTS[action_idx]

        # Constraint 1: Quiet hours.
        if is_in_quiet_hours(slot_minutes):
            continue

        # Constraint 2: Deadline enforcement.
        # If the message has a deadline, the slot must be before it.
        deadline = message.get("deadline")
        if deadline:
            deadline_minutes = deadline.hour * 60 + deadline.minute
            if slot_minutes > deadline_minutes:
                continue

        # This slot passes all constraints. Use it.
        return action_idx

    # Fallback: no slot passed. Use the first non-quiet-hours slot.
    # This shouldn't happen in practice (we have 28 daytime slots).
    logger.warning("No slot passed constraints. Using first available.")
    return 0
```

---

## Step 3: Select Optimal Send Time

*This is the core decision function. It combines the LinUCB agent's recommendation with safety constraints to produce a final send time.*

```python
def select_send_time(
    agent: LinUCBAgent,
    patient_context: dict,
    message: dict,
) -> dict:
    """
    Use the bandit agent to select the optimal send time for a message.

    Combines the model's recommendation with safety constraint enforcement.

    Args:
        agent: The trained LinUCB agent.
        patient_context: Patient engagement data from DynamoDB.
        message: Message metadata (type, channel, urgency, deadline).

    Returns:
        Dict with selected_slot (minutes), time_str, action_index, and score.
    """
    # Build the context feature vector.
    context = build_context_features(patient_context, message)

    # Get UCB scores for all actions.
    # We need the full ranking (not just the top pick) so we can apply
    # safety constraints and fall through to the next-best option.
    ucb_scores = []
    for a in range(agent.n_actions):
        A_inv = np.linalg.inv(agent.A[a])
        theta = A_inv @ agent.b[a]
        predicted = context @ theta
        uncertainty = np.sqrt(context @ A_inv @ context)
        score = predicted + agent.alpha * uncertainty
        ucb_scores.append((a, score))

    # Sort by score descending (best first).
    ranked = sorted(ucb_scores, key=lambda x: x[1], reverse=True)

    # Apply safety constraints to find the best valid slot.
    selected_action = apply_safety_constraints(ranked, patient_context, message)
    selected_slot = TIME_SLOTS[selected_action]
    selected_score = ucb_scores[selected_action][1]

    return {
        "action_index": selected_action,
        "selected_slot_minutes": selected_slot,
        "time_str": slot_to_time_str(selected_slot),
        "score": round(selected_score, 4),
        "context_features": context.tolist(),
    }
```

---

## Step 4: Record Engagement and Update Model

*The pseudocode calls this `process_engagement_event(event)`. Here we map engagement outcomes to rewards and feed them back to the agent for learning.*

```python
def compute_reward(event_type: str) -> float:
    """
    Map an engagement event type to a numeric reward value.

    Args:
        event_type: One of the keys in REWARD_MAP.

    Returns:
        The reward value. Unknown event types get 0.0 (neutral).
    """
    reward = REWARD_MAP.get(event_type, 0.0)
    return reward

def update_agent_with_outcome(
    agent: LinUCBAgent,
    decision_record: dict,
    event_type: str,
):
    """
    Feed an engagement outcome back to the agent for learning.

    This closes the learning loop. Without this step, the agent never improves.

    Args:
        agent: The LinUCB agent to update.
        decision_record: The stored decision (contains action_index and context_features).
        event_type: The engagement outcome (key from REWARD_MAP).
    """
    reward = compute_reward(event_type)
    action = decision_record["action_index"]
    context = np.array(decision_record["context_features"])

    # Update the agent's model for this action.
    agent.update(action, context, reward)

    logger.info(
        "Updated agent: action=%d (%s), reward=%.2f, event=%s",
        action,
        slot_to_time_str(TIME_SLOTS[action]),
        reward,
        event_type,
    )
```

---

## Step 5: Update Patient Context

*After each engagement outcome, update the patient's stored features so future decisions reflect their latest behavior.*

```python
def update_patient_context(patient_id: str, event_type: str):
    """
    Update the patient's engagement history in DynamoDB after an outcome.

    Recalculates rolling engagement rates and fatigue score.
    In production, you'd use atomic counters and conditional updates
    to handle concurrent writes safely.

    Args:
        patient_id: The patient whose context to update.
        event_type: The engagement outcome type.
    """
    table = dynamodb.Table(PATIENT_TABLE_NAME)

    # Increment the appropriate counter based on outcome.
    # This is simplified. Production would maintain rolling 30-day windows.
    update_expr = "SET last_engagement_time = :now"
    expr_values = {":now": datetime.datetime.now(timezone.utc).isoformat()}

    if event_type in ("action_completed", "link_clicked", "message_opened"):
        update_expr += ", messages_engaged = if_not_exists(messages_engaged, :zero) + :one"
        expr_values[":one"] = 1
        expr_values[":zero"] = 0
    elif event_type == "ignored":
        update_expr += ", fatigue_score = if_not_exists(fatigue_score, :zero) + :fatigue_inc"
        expr_values[":fatigue_inc"] = Decimal("0.05")
        expr_values[":zero"] = Decimal("0")
    elif event_type == "unsubscribed":
        update_expr += ", channel_active = :false_val"
        expr_values[":false_val"] = False

    table.update_item(
        Key={"patient_id": patient_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    logger.info("Updated context for patient %s after %s", patient_id, event_type)
```

---

## Putting It All Together

Here's the full pipeline assembled into a simulation that demonstrates the learning loop. Since we can't actually send messages and wait for engagement in a code example, we simulate patient behavior to show how the agent improves over time.

```python
import json
import random

def simulate_patient_engagement(slot_minutes: int, patient_prefs: dict) -> str:
    """
    Simulate whether a patient engages with a message sent at a given time.

    This replaces real engagement tracking for demonstration purposes.
    Each simulated patient has preferred hours where engagement probability is higher.

    Args:
        slot_minutes: When the message was sent (minutes from midnight).
        patient_prefs: Dict with 'preferred_hours' (list of hour ints) and
                       'base_engagement_rate' (float).

    Returns:
        An event type string (key from REWARD_MAP).
    """
    hour = slot_minutes // 60
    preferred = patient_prefs.get("preferred_hours", [18, 19, 20])
    base_rate = patient_prefs.get("base_engagement_rate", 0.1)

    # Engagement probability is 3x higher during preferred hours.
    if hour in preferred:
        engage_prob = min(base_rate * 3.0, 0.9)
    else:
        engage_prob = base_rate

    roll = random.random()
    if roll < engage_prob * 0.4:
        return "action_completed"
    elif roll < engage_prob * 0.7:
        return "message_opened"
    elif roll < engage_prob:
        return "link_clicked"
    else:
        return "ignored"

def run_notification_timing_simulation():
    """
    Run a full simulation demonstrating the learning loop.

    Creates a LinUCB agent, simulates 500 message sends to a patient with
    known preferences, and shows how the agent converges on the optimal timing.
    """
    print("=" * 60)
    print("Notification Timing Optimization: LinUCB Simulation")
    print("=" * 60)

    # Initialize the agent.
    agent = LinUCBAgent(
        n_actions=NUM_ACTIONS,
        n_features=FEATURE_DIM,
        alpha=LINUCB_ALPHA,
    )

    # Simulated patient: prefers evening messages (6pm-8pm).
    patient_prefs = {
        "preferred_hours": [18, 19, 20],
        "base_engagement_rate": 0.15,
    }

    # Simulated patient context (what we'd fetch from DynamoDB).
    patient_context = {
        "patient_id": "pat-sim-001",
        "open_rate_30d": Decimal("0.15"),
        "action_rate_30d": Decimal("0.05"),
        "days_since_last_send": Decimal("3"),
        "recent_message_count": 1,
        "fatigue_score": Decimal("0.1"),
        "age_bucket": 6,
        "timezone": "America/New_York",
        "messages_today": 0,
    }

    message = {
        "type": "refill_reminder",
        "channel": "push",
        "urgency": "normal",
        "deadline": None,
    }

    # Track results over time to show learning.
    results_by_epoch = []
    epoch_size = 50

    for episode in range(500):
        # Step 1: Select send time using the agent.
        decision = select_send_time(agent, patient_context, message)

        # Step 2: Simulate patient engagement at the selected time.
        event_type = simulate_patient_engagement(
            decision["selected_slot_minutes"], patient_prefs
        )

        # Step 3: Compute reward and update the agent.
        reward = compute_reward(event_type)
        context = np.array(decision["context_features"])
        agent.update(decision["action_index"], context, reward)

        # Track for reporting.
        results_by_epoch.append({
            "episode": episode,
            "slot": decision["time_str"],
            "event": event_type,
            "reward": reward,
        })

        # Print progress every epoch_size episodes.
        if (episode + 1) % epoch_size == 0:
            epoch_results = results_by_epoch[-epoch_size:]
            avg_reward = sum(r["reward"] for r in epoch_results) / epoch_size
            action_rate = sum(
                1 for r in epoch_results if r["event"] == "action_completed"
            ) / epoch_size

            # What time slots is the agent choosing most often?
            slot_counts = {}
            for r in epoch_results:
                slot_counts[r["slot"]] = slot_counts.get(r["slot"], 0) + 1
            top_slot = max(slot_counts, key=slot_counts.get)

            print(f"\nEpisodes {episode - epoch_size + 2}-{episode + 1}:")
            print(f"  Avg reward:       {avg_reward:.3f}")
            print(f"  Action rate:      {action_rate:.1%}")
            print(f"  Most chosen slot: {top_slot} ({slot_counts[top_slot]}/{epoch_size} times)")

    # Final summary.
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)

    # Compare first 100 episodes vs last 100.
    early = results_by_epoch[:100]
    late = results_by_epoch[-100:]

    early_reward = sum(r["reward"] for r in early) / 100
    late_reward = sum(r["reward"] for r in late) / 100
    early_actions = sum(1 for r in early if r["event"] == "action_completed") / 100
    late_actions = sum(1 for r in late if r["event"] == "action_completed") / 100

    print(f"\nFirst 100 episodes:  avg_reward={early_reward:.3f}, action_rate={early_actions:.1%}")
    print(f"Last 100 episodes:   avg_reward={late_reward:.3f}, action_rate={late_actions:.1%}")
    print(f"Improvement:         {((late_reward - early_reward) / max(early_reward, 0.01)) * 100:.0f}% reward lift")

    # Show the agent's learned time preferences.
    print("\nLearned slot preferences (top 5 by UCB score):")
    context = build_context_features(patient_context, message)
    scores = []
    for a in range(agent.n_actions):
        A_inv = np.linalg.inv(agent.A[a])
        theta = A_inv @ agent.b[a]
        predicted = context @ theta
        scores.append((a, predicted))

    scores.sort(key=lambda x: x[1], reverse=True)
    for a, score in scores[:5]:
        print(f"  {slot_to_time_str(TIME_SLOTS[a])}: predicted_reward={score:.4f}")

    print("\nPatient's actual preferred hours: 6pm-8pm")
    print("(The agent should converge toward these evening slots.)")

# Run the simulation.
if __name__ == "__main__":
    run_notification_timing_simulation()
```

---

## The Gap Between This and Production

This example demonstrates the core RL concepts: state representation, action selection with exploration, reward computation, and the learning loop. But there's a meaningful distance between this simulation and a deployed notification timing system. Here's where that gap lives:

**Amazon Personalize instead of hand-rolled LinUCB.** In production, you'd use Personalize's contextual bandit recipe rather than implementing LinUCB yourself. Personalize handles algorithm selection, hyperparameter tuning, model retraining, and real-time inference at scale. It also manages the exploration/exploitation tradeoff automatically. The hand-rolled version here is for understanding the mechanics; Personalize is for deploying them.

**Persistent model state.** The LinUCB agent here lives in memory and dies when the process exits. A production system persists the model parameters (the A matrices and b vectors, or the Personalize campaign) so learning accumulates across invocations. With Personalize, this is handled automatically through the interactions dataset and periodic retraining.

**Real engagement tracking.** This example simulates engagement. A production system integrates with Pinpoint's event stream (opens, clicks) and your application's action tracking (prescription refilled, appointment scheduled). Events arrive asynchronously, sometimes hours after delivery. You need a reliable event pipeline (Kinesis, EventBridge) to capture them and attribute them back to the original send decision.

**Timezone handling.** The example ignores timezones entirely. A production system must convert all time slots to the patient's local timezone before applying quiet hours and before interpreting "6pm" as a slot. Patients in different timezones need different slot interpretations. Store timezone per patient and convert at decision time.

**Multi-message coordination.** If three messages are pending for the same patient, this code would independently select the optimal time for each one, potentially stacking them all at 6:30pm. A production system needs a coordination layer that spaces messages out and prioritizes by urgency.

**Error handling and retries.** Every DynamoDB call, every Personalize inference, every EventBridge schedule creation can fail. Production code wraps each in try/except with specific handling for throttling (exponential backoff), service errors (retry with circuit breaker), and validation errors (log and skip).

**IAM least-privilege.** The permissions listed in Setup are broader than necessary. Production scopes each permission to specific resources: `dynamodb:GetItem` on the specific table ARN, `scheduler:CreateSchedule` with a condition on the schedule group, etc.

**VPC and encryption.** Patient engagement data is PHI. Production runs Lambda in a VPC with endpoints for DynamoDB, Kinesis, and Personalize. All data at rest uses KMS customer-managed keys. All transit is TLS. The example doesn't address any of this.

**Monitoring and alerting.** Production needs CloudWatch metrics on: decisions per minute, average reward over time, exploration rate, constraint violations, delivery failures, and model staleness (time since last retrain). Alarms fire if engagement drops below baseline (the model is hurting rather than helping) or if opt-out rate spikes.

**A/B testing framework.** Before deploying the RL model, you need a holdout group that continues receiving messages at static times. This lets you measure the actual lift from timing optimization and detect regressions. The holdout should be at least 10% of patients, maintained indefinitely.

**DynamoDB Decimal handling.** This example already uses `Decimal` for numeric values stored in DynamoDB (see the patient context). Any new numeric fields you add must also use `Decimal`. The boto3 DynamoDB resource layer raises a `TypeError` on raw floats in `put_item` or `update_item` calls.

**Cold start strategy.** The example uses flat population defaults for new patients. Production should cluster patients by demographics (age, condition type, channel preference) and use cluster-level timing priors. A new 70-year-old retiree should inherit evening-preference priors from similar retirees, not the global average dominated by working-age adults checking phones during commutes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 15.2](chapter15.02-notification-timing-optimization.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
