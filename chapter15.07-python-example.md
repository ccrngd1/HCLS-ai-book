# Recipe 15.7: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the RL concepts from Recipe 15.7. It demonstrates the shape of a chronic disease treatment personalization system: patient environment modeling, multi-year state tracking, offline policy learning with batch-constrained Q-learning, safety constraint enforcement, and treatment recommendation generation. This is absolutely not production-ready. Chronic disease RL operates over months and years, requires extensive retrospective validation, prospective clinical trials, and likely FDA clearance before influencing any treatment decision. Consider this a learning tool for understanding how RL applies to long-horizon treatment optimization, not something you'd connect to a prescribing system.

---

## Setup

```bash
pip install boto3 numpy
```

Your environment needs AWS credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query`, `s3:GetObject`, `s3:PutObject`, and `cloudwatch:PutMetricData`. You'll need a signed BAA because longitudinal treatment data is PHI regardless of de-identification status.

---

## Config and Constants

Before the logic, here's the configuration that defines the chronic disease treatment MDP. These constants encode clinical knowledge about type 2 diabetes management: what outcomes matter, how to score them, what treatment transitions are safe, and what the action space looks like. In a real system, these would be developed with endocrinologists, validated against clinical practice guidelines (ADA Standards of Care), and reviewed by your institution's pharmacy committee.

```python
import json
import time
import uuid
import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import boto3
import numpy as np
from botocore.config import Config

# Structured logging. Never log patient identifiers or PHI values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS calls.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# =============================================================================
# CLINICAL DOMAIN: TYPE 2 DIABETES MANAGEMENT
# =============================================================================
# This example focuses on type 2 diabetes because it has:
# - Clear outcome metrics (HbA1c, hypoglycemia events)
# - Well-defined treatment escalation pathways
# - Multi-year time horizons where personalization matters
# - Enough clinical trial data to validate against

# --- Outcome Targets ---
# HbA1c is the primary outcome: a 3-month average of blood glucose control.
# The ADA recommends < 7% for most adults, but individualized targets matter.
# Older patients or those with comorbidities may have relaxed targets (< 8%).
HBA1C_TARGET = 7.0          # % : standard target for most adults
HBA1C_RELAXED_TARGET = 8.0  # % : relaxed target for frail/elderly/comorbid
HBA1C_DANGEROUS_LOW = 5.5   # % : below this suggests over-treatment risk
HBA1C_DANGEROUS_HIGH = 10.0 # % : above this risks microvascular complications

# --- Decision Interval ---
# Unlike ICU settings (hours), chronic disease decisions happen quarterly.
# HbA1c reflects ~3 months of glucose control, so treatment changes need
# at least 3 months to show effect. Changing faster causes oscillation.
DECISION_INTERVAL_MONTHS = 3

# --- Action Space ---
# Treatment actions for type 2 diabetes, ordered by escalation level.
# Each action represents a treatment regimen, not a single drug.
# The agent picks one of these at each quarterly decision point.
TREATMENT_ACTIONS = [
    {"id": 0, "name": "lifestyle_only",
     "desc": "Diet, exercise, weight management. No medications."},
    {"id": 1, "name": "metformin_monotherapy",
     "desc": "First-line oral: metformin 500-2000mg daily."},
    {"id": 2, "name": "metformin_plus_sglt2",
     "desc": "Dual oral: metformin + SGLT2 inhibitor (empagliflozin, dapagliflozin)."},
    {"id": 3, "name": "metformin_plus_glp1",
     "desc": "Metformin + GLP-1 receptor agonist (semaglutide, liraglutide)."},
    {"id": 4, "name": "metformin_plus_dpp4",
     "desc": "Metformin + DPP-4 inhibitor (sitagliptin). Less potent but well-tolerated."},
    {"id": 5, "name": "triple_oral",
     "desc": "Metformin + SGLT2 + DPP-4. Maximum oral therapy before injectables."},
    {"id": 6, "name": "metformin_plus_basal_insulin",
     "desc": "Oral + basal insulin (glargine, degludec). Major escalation step."},
    {"id": 7, "name": "intensive_insulin",
     "desc": "Basal-bolus insulin regimen. Maximum pharmacological intervention."},
]
NUM_ACTIONS = len(TREATMENT_ACTIONS)

# --- State Features ---
# The state captures everything relevant to a treatment decision.
# Chronic disease RL has a much richer patient context than acute care
# because you have years of history and lifestyle factors matter enormously.
STATE_FEATURES = [
    # Primary outcome and trend
    {"name": "hba1c_current", "min": 4.0, "max": 14.0,
     "why": "Current HbA1c: the primary metric driving treatment decisions"},
    {"name": "hba1c_prev_quarter", "min": 4.0, "max": 14.0,
     "why": "Previous quarter's HbA1c for trend detection"},
    {"name": "hba1c_trend", "min": -2.0, "max": 2.0,
     "why": "Rate of change per quarter; negative means improving"},
    # Hypoglycemia burden
    {"name": "hypo_events_quarter", "min": 0, "max": 20,
     "why": "Number of hypoglycemic episodes in past quarter"},
    {"name": "severe_hypo_ever", "min": 0, "max": 1,
     "why": "Binary: ever had severe hypoglycemia requiring assistance"},
    # Current treatment
    {"name": "current_treatment_level", "min": 0, "max": 7,
     "why": "Current treatment action index (for transition constraints)"},
    {"name": "months_on_current_treatment", "min": 0, "max": 60,
     "why": "Duration on current regimen; short duration means give it more time"},
    # Patient factors
    {"name": "age", "min": 18, "max": 95,
     "why": "Older patients get relaxed targets and avoid hypoglycemia risk"},
    {"name": "bmi", "min": 18, "max": 55,
     "why": "Obesity affects drug choice (GLP-1 agonists help with weight)"},
    {"name": "egfr", "min": 10, "max": 120,
     "why": "Kidney function; metformin contraindicated below 30, SGLT2 less effective below 45"},
    {"name": "cardiovascular_risk", "min": 0, "max": 1,
     "why": "Binary: established CVD or high risk. Favors SGLT2/GLP-1 agents."},
    {"name": "heart_failure", "min": 0, "max": 1,
     "why": "Binary: heart failure present. Strongly favors SGLT2 inhibitors."},
    # Adherence and engagement
    {"name": "medication_adherence", "min": 0, "max": 1.0,
     "why": "Proportion of days covered (PDC). Low adherence means escalation may not help."},
    {"name": "appointment_adherence", "min": 0, "max": 1.0,
     "why": "Fraction of scheduled visits attended. Proxy for engagement."},
    # Comorbidity burden
    {"name": "comorbidity_count", "min": 0, "max": 10,
     "why": "Number of active comorbidities. More = more conservative targets."},
    {"name": "diabetes_duration_years", "min": 0, "max": 40,
     "why": "Longer duration = more beta-cell loss = harder to control with orals."},
]
NUM_STATE_FEATURES = len(STATE_FEATURES)

# --- Safety Constraints ---
# Hard rules that override the RL policy. These encode clinical guidelines
# and contraindications that should never be violated.
SAFETY_CONSTRAINTS = {
    # Never escalate more than 2 levels at once (e.g., lifestyle -> triple oral is too aggressive)
    "max_escalation_steps": 2,
    # Never de-escalate more than 1 level at once (avoid rebound hyperglycemia)
    "max_deescalation_steps": 1,
    # Minimum time on current treatment before changing (give it time to work)
    "min_months_before_change": 3,
    # Don't escalate if adherence is below this (fix adherence first)
    "min_adherence_for_escalation": 0.6,
    # Metformin contraindicated below this eGFR
    "metformin_egfr_floor": 30,
    # SGLT2 less effective below this eGFR
    "sglt2_egfr_floor": 45,
    # Don't use insulin-heavy regimens if severe hypo history + age > 75
    "insulin_age_hypo_limit": 75,
    # If HbA1c is already at target, don't escalate
    "no_escalation_at_target": True,
}

# --- Reward Function Parameters ---
# The reward encodes what "good diabetes management" means over time.
# Key insight: chronic disease reward is multi-objective. You want low HbA1c
# BUT also low hypoglycemia, good tolerability, and minimal treatment burden.
REWARD_PARAMS = {
    "at_target_reward": 10.0,         # HbA1c at individualized target
    "improving_bonus": 3.0,           # HbA1c trending down toward target
    "above_target_penalty_scale": -2.0,  # per 0.5% above target
    "dangerous_high_penalty": -15.0,  # HbA1c > 10%
    "over_treatment_penalty": -8.0,   # HbA1c < 5.5% (too aggressive)
    "hypo_event_penalty": -5.0,       # per hypoglycemic episode
    "severe_hypo_penalty": -20.0,     # severe hypoglycemia (catastrophic)
    "treatment_burden_scale": -0.5,   # per escalation level (prefer simpler regimens)
    "unnecessary_escalation": -3.0,   # escalating when already at target
    "adherence_mismatch": -4.0,       # escalating when adherence is poor
}

# --- AWS Resource Names ---
SAGEMAKER_ENDPOINT = "chronic-dm-rl-policy-v1"
DYNAMODB_TABLE = "patient-diabetes-state"
S3_TRAINING_BUCKET = "chronic-dm-rl-training"
S3_EPISODE_PREFIX = "episodes/dm-type2/"
```

---

## Step 1: Reward Function

*The reward function is the most consequential design decision. Chronic disease RL has a fundamentally different reward structure than acute care: outcomes unfold over months, multiple objectives compete, and treatment burden itself is a cost. You can't just optimize HbA1c; you have to balance glycemic control against hypoglycemia risk, side effects, and regimen complexity.*

```python
def compute_reward(
    hba1c: float,
    target_hba1c: float,
    hypo_events: int,
    severe_hypo: bool,
    treatment_level: int,
    previous_treatment_level: int,
    adherence: float,
) -> float:
    """
    Compute the reward for a quarterly treatment outcome.

    This is multi-objective by design. A perfect HbA1c achieved through
    aggressive insulin that causes frequent hypoglycemia is NOT a good outcome.
    A slightly elevated HbA1c on a simple oral regimen with no side effects
    might be better for that patient's quality of life.

    The reward function encodes these trade-offs:
    1. Primary: Is HbA1c at the individualized target?
    2. Safety: Any hypoglycemia events? (heavily penalized)
    3. Burden: Is the treatment regimen more complex than necessary?
    4. Appropriateness: Did we escalate when adherence was the real problem?

    Args:
        hba1c: Current HbA1c measurement (%).
        target_hba1c: Individualized target for this patient (%).
        hypo_events: Number of hypoglycemic episodes this quarter.
        severe_hypo: Whether any severe hypoglycemia occurred.
        treatment_level: Current treatment action index (0-7).
        previous_treatment_level: Treatment level at start of quarter.
        adherence: Medication adherence proportion (0-1).

    Returns:
        Float reward value. Higher is better.
    """
    reward = 0.0

    # --- Glycemic control component ---
    if hba1c < HBA1C_DANGEROUS_LOW:
        # Over-treated. HbA1c this low in a type 2 patient means the regimen
        # is too aggressive. High risk of hypoglycemia.
        reward += REWARD_PARAMS["over_treatment_penalty"]

    elif abs(hba1c - target_hba1c) <= 0.3:
        # At target (within 0.3% tolerance). This is the goal state.
        reward += REWARD_PARAMS["at_target_reward"]

    elif hba1c > HBA1C_DANGEROUS_HIGH:
        # Dangerously high. Microvascular damage accumulating.
        reward += REWARD_PARAMS["dangerous_high_penalty"]

    elif hba1c > target_hba1c:
        # Above target but not dangerous. Scaled penalty.
        overshoot = hba1c - target_hba1c
        reward += REWARD_PARAMS["above_target_penalty_scale"] * (overshoot / 0.5)

    else:
        # Below target but not dangerously low. Mild positive.
        reward += REWARD_PARAMS["at_target_reward"] * 0.5

    # --- Hypoglycemia component ---
    # Each hypo event is penalized. Severe hypo gets a massive penalty.
    # This makes the agent deeply afraid of over-treatment.
    reward += REWARD_PARAMS["hypo_event_penalty"] * hypo_events
    if severe_hypo:
        reward += REWARD_PARAMS["severe_hypo_penalty"]

    # --- Treatment burden component ---
    # Prefer simpler regimens when outcomes are equivalent.
    # A patient controlled on metformin alone is better off than one
    # controlled on triple therapy, all else being equal.
    reward += REWARD_PARAMS["treatment_burden_scale"] * treatment_level

    # --- Appropriateness penalties ---
    escalated = treatment_level > previous_treatment_level
    if escalated and hba1c <= target_hba1c + 0.3:
        # Escalated when already at target. Unnecessary complexity.
        reward += REWARD_PARAMS["unnecessary_escalation"]

    if escalated and adherence < SAFETY_CONSTRAINTS["min_adherence_for_escalation"]:
        # Escalated when the patient isn't taking their current meds.
        # The problem is adherence, not pharmacology.
        reward += REWARD_PARAMS["adherence_mismatch"]

    return round(reward, 2)
```

---

## Step 2: State Construction

*Transforms raw patient data from the longitudinal record into a normalized state vector. Chronic disease state is richer than acute care because you have years of history and lifestyle factors that matter enormously for treatment response.*

```python
def normalize_feature(value: float, feature_def: dict) -> float:
    """
    Normalize a raw clinical value to [0, 1] using defined bounds.

    Clipping to bounds handles physiologically extreme values gracefully.
    """
    min_val = feature_def["min"]
    max_val = feature_def["max"]
    clipped = max(min_val, min(max_val, value))
    if max_val == min_val:
        return 0.5
    return (clipped - min_val) / (max_val - min_val)


def construct_state_vector(patient_data: dict) -> np.ndarray:
    """
    Build a normalized state vector from patient's current clinical state.

    Missing values get midpoint imputation. In production, you'd use the
    last known value with a staleness indicator, or a learned imputation
    model trained on the same population.

    Args:
        patient_data: Dict mapping feature names to current values.

    Returns:
        numpy array of shape (NUM_STATE_FEATURES,) with values in [0, 1].
    """
    state = np.zeros(NUM_STATE_FEATURES, dtype=np.float32)

    for i, feature_def in enumerate(STATE_FEATURES):
        name = feature_def["name"]
        if name in patient_data and patient_data[name] is not None:
            state[i] = normalize_feature(patient_data[name], feature_def)
        else:
            state[i] = 0.5
            logger.warning("Missing feature '%s', using midpoint imputation", name)

    return state


def compute_individualized_target(patient_data: dict) -> float:
    """
    Determine the individualized HbA1c target for this patient.

    ADA guidelines recommend relaxed targets for:
    - Elderly patients (> 75 years)
    - Patients with multiple comorbidities
    - Patients with history of severe hypoglycemia
    - Patients with limited life expectancy

    This is a simplified version. Real clinical decision-making considers
    many more factors and involves shared decision-making with the patient.

    Args:
        patient_data: Patient's clinical state.

    Returns:
        Individualized HbA1c target (%).
    """
    target = HBA1C_TARGET  # Start with standard 7.0%

    age = patient_data.get("age", 50)
    comorbidities = patient_data.get("comorbidity_count", 0)
    severe_hypo = patient_data.get("severe_hypo_ever", 0)

    # Relax target for elderly
    if age > 75:
        target = max(target, 7.5)
    if age > 80:
        target = max(target, 8.0)

    # Relax for high comorbidity burden
    if comorbidities >= 5:
        target = max(target, 7.5)

    # Relax if history of severe hypoglycemia
    if severe_hypo:
        target = max(target, 7.5)

    return min(target, HBA1C_RELAXED_TARGET)
```

---

## Step 3: Safety Constraint Layer

*The safety layer enforces clinical guidelines and contraindications that override the RL policy. In chronic disease management, these constraints encode years of clinical trial evidence about what treatment transitions are safe and appropriate.*

```python
def apply_safety_constraints(
    recommended_action: int,
    patient_data: dict,
) -> dict:
    """
    Apply clinical safety constraints to the RL policy's treatment recommendation.

    Chronic disease constraints are different from acute care. They're less about
    preventing immediate harm and more about preventing inappropriate treatment
    transitions that waste time, cause side effects, or ignore the real problem.

    The constraints encode:
    1. Maximum escalation/de-escalation speed
    2. Minimum time on current treatment before switching
    3. Contraindications based on renal function
    4. Adherence-gating (don't escalate if patient isn't taking current meds)
    5. Age/frailty-based insulin avoidance

    Args:
        recommended_action: Treatment action index the RL policy wants.
        patient_data: Current patient state (raw values).

    Returns:
        Dict with final_action, original_recommendation, and activated constraints.
    """
    current_level = int(patient_data.get("current_treatment_level", 0))
    safe_action = recommended_action
    activated = []

    # Constraint 1: Maximum escalation speed.
    # Don't jump from lifestyle to insulin in one step. Patients need time
    # to adjust, and intermediate options may work.
    max_up = SAFETY_CONSTRAINTS["max_escalation_steps"]
    if safe_action > current_level + max_up:
        safe_action = current_level + max_up
        activated.append(
            f"max_escalation: capped at +{max_up} steps "
            f"(wanted {recommended_action}, got {safe_action})"
        )

    # Constraint 2: Maximum de-escalation speed.
    # Don't drop multiple levels at once; rebound hyperglycemia is real.
    max_down = SAFETY_CONSTRAINTS["max_deescalation_steps"]
    if safe_action < current_level - max_down:
        safe_action = current_level - max_down
        activated.append(
            f"max_deescalation: capped at -{max_down} steps"
        )

    # Constraint 3: Minimum time before changing.
    # HbA1c takes 3 months to reflect a treatment change. Switching sooner
    # means you never saw the effect of the current regimen.
    months_on_current = patient_data.get("months_on_current_treatment", 0)
    min_months = SAFETY_CONSTRAINTS["min_months_before_change"]
    if safe_action != current_level and months_on_current < min_months:
        safe_action = current_level
        activated.append(
            f"min_duration_hold: only {months_on_current} months on current "
            f"(need {min_months}), holding"
        )

    # Constraint 4: Adherence gating.
    # If the patient isn't taking their current medications, adding more
    # medications won't help. Fix adherence first.
    adherence = patient_data.get("medication_adherence", 1.0)
    min_adherence = SAFETY_CONSTRAINTS["min_adherence_for_escalation"]
    if safe_action > current_level and adherence < min_adherence:
        safe_action = current_level
        activated.append(
            f"adherence_gate: adherence={adherence:.0%} < {min_adherence:.0%}, "
            f"holding (address adherence first)"
        )

    # Constraint 5: Renal contraindications.
    # NOTE: Contraindications override duration holds (Constraint 3) because
    # safety trumps "give it more time." If eGFR drops below threshold while
    # on metformin, the drug must be stopped regardless of duration.
    egfr = patient_data.get("egfr", 90)
    # Metformin contraindicated below eGFR 30
    if safe_action >= 1 and egfr < SAFETY_CONSTRAINTS["metformin_egfr_floor"]:
        # Can't use metformin-containing regimens. Skip to insulin if needed.
        if safe_action <= 5:
            safe_action = 0  # Fall back to lifestyle (or direct to insulin)
            activated.append(
                f"metformin_contraindicated: eGFR={egfr}, "
                f"metformin-based regimens unavailable"
            )

    # SGLT2 less effective below eGFR 45
    if safe_action in [2, 5] and egfr < SAFETY_CONSTRAINTS["sglt2_egfr_floor"]:
        # Switch SGLT2-containing regimens to alternatives
        if safe_action == 2:
            safe_action = 3  # Use GLP-1 instead of SGLT2
        elif safe_action == 5:
            safe_action = 4  # Use DPP-4 instead of triple with SGLT2
        activated.append(
            f"sglt2_renal_limit: eGFR={egfr}, SGLT2 less effective, "
            f"switched to alternative"
        )

    # Constraint 6: Insulin avoidance in elderly with hypo history.
    age = patient_data.get("age", 50)
    severe_hypo = patient_data.get("severe_hypo_ever", 0)
    if safe_action >= 6 and age > SAFETY_CONSTRAINTS["insulin_age_hypo_limit"] and severe_hypo:
        safe_action = min(safe_action, 5)  # Cap at maximum oral therapy
        activated.append(
            f"insulin_safety_cap: age={age}, severe hypo history, "
            f"avoiding insulin regimens"
        )

    # Constraint 7: Don't escalate if already at target.
    if SAFETY_CONSTRAINTS["no_escalation_at_target"]:
        hba1c = patient_data.get("hba1c_current", 7.0)
        target = compute_individualized_target(patient_data)
        if safe_action > current_level and hba1c <= target + 0.3:
            safe_action = current_level
            activated.append(
                f"at_target_hold: HbA1c={hba1c:.1f}% within target "
                f"({target:.1f}%), no escalation needed"
            )

    # Floor at 0 (can't go below lifestyle only)
    safe_action = max(0, safe_action)

    return {
        "final_action": safe_action,
        "final_treatment": TREATMENT_ACTIONS[safe_action]["name"],
        "original_recommendation": recommended_action,
        "original_treatment": TREATMENT_ACTIONS[recommended_action]["name"],
        "constraints_activated": activated,
    }
```

---

## Step 4: Episode Construction from Longitudinal Records

*Transforms years of patient treatment history into RL episodes. This is where chronic disease RL gets hard: you're working with sparse, irregularly-spaced observations over multi-year horizons. A single patient might have 20 quarterly observations spanning 5 years of treatment.*

```python
def build_episode_from_patient_history(patient_record: dict) -> list:
    """
    Convert a patient's longitudinal diabetes record into an RL episode.

    Each transition represents one quarterly decision point:
    - State: patient's clinical status at the decision time
    - Action: what treatment the clinician chose
    - Reward: outcome observed at the NEXT quarterly visit
    - Next state: patient's status at the next visit

    The hard parts (which this simplified version glosses over):
    - Irregular visit spacing (not everyone comes back in exactly 3 months)
    - Missing labs (HbA1c not drawn every visit)
    - Treatment changes between visits (patient stopped meds on their own)
    - Confounders (patient started exercising AND changed meds)

    Args:
        patient_record: Dict with keys:
            - "visits": list of quarterly visit records, each containing:
                - "hba1c", "hypo_events", "treatment_level", "adherence",
                  "egfr", "bmi", "age", "comorbidities", etc.
            - "patient_info": static demographics

    Returns:
        List of transition dicts: {state, action, reward, next_state}
    """
    visits = patient_record.get("visits", [])
    patient_info = patient_record.get("patient_info", {})

    if len(visits) < 3:
        return []  # Need at least 3 visits for state + action + outcome

    episode = []

    for i in range(1, len(visits) - 1):
        prev_visit = visits[i - 1]
        current_visit = visits[i]
        next_visit = visits[i + 1]

        # Build state from current visit
        hba1c_current = current_visit.get("hba1c", 7.0)
        hba1c_prev = prev_visit.get("hba1c", hba1c_current)
        # HbA1c trend: difference between this quarter and last quarter.
        # This gives rate of change per quarter (not per month), matching
        # the STATE_FEATURES bounds of [-2.0, 2.0].
        hba1c_trend = hba1c_current - hba1c_prev

        state_data = {
            "hba1c_current": hba1c_current,
            "hba1c_prev_quarter": hba1c_prev,
            "hba1c_trend": hba1c_trend,
            "hypo_events_quarter": current_visit.get("hypo_events", 0),
            "severe_hypo_ever": patient_info.get("severe_hypo_ever", 0),
            "current_treatment_level": current_visit.get("treatment_level", 0),
            "months_on_current_treatment": current_visit.get("months_on_treatment", 3),
            "age": patient_info.get("age", 55),
            "bmi": current_visit.get("bmi", 28),
            "egfr": current_visit.get("egfr", 80),
            "cardiovascular_risk": patient_info.get("cv_risk", 0),
            "heart_failure": patient_info.get("heart_failure", 0),
            "medication_adherence": current_visit.get("adherence", 0.8),
            "appointment_adherence": patient_info.get("appt_adherence", 0.9),
            "comorbidity_count": patient_info.get("comorbidity_count", 2),
            "diabetes_duration_years": patient_info.get("diabetes_duration", 5),
        }

        state_vector = construct_state_vector(state_data)

        # Action: what treatment the clinician chose at this visit
        action = current_visit.get("treatment_level", 0)

        # Reward: based on outcome at the NEXT visit
        # This is the key temporal structure: the reward for today's decision
        # isn't observed until 3 months later.
        target = compute_individualized_target(state_data)
        next_hba1c = next_visit.get("hba1c", 7.0)
        next_hypo = next_visit.get("hypo_events", 0)
        next_severe = next_visit.get("severe_hypo", False)

        reward = compute_reward(
            hba1c=next_hba1c,
            target_hba1c=target,
            hypo_events=next_hypo,
            severe_hypo=next_severe,
            treatment_level=action,
            previous_treatment_level=prev_visit.get("treatment_level", 0),
            adherence=current_visit.get("adherence", 0.8),
        )

        # Next state
        next_state_data = {
            **state_data,
            "hba1c_current": next_hba1c,
            "hba1c_prev_quarter": hba1c_current,
            "hba1c_trend": next_hba1c - hba1c_current,
            "hypo_events_quarter": next_hypo,
            "current_treatment_level": action,
            "months_on_current_treatment": next_visit.get("months_on_treatment", 3),
        }
        next_state_vector = construct_state_vector(next_state_data)

        episode.append({
            "state": state_vector.tolist(),
            "action": action,
            "reward": reward,
            "next_state": next_state_vector.tolist(),
        })

    return episode
```

---

## Step 5: Offline RL Training (Batch-Constrained Q-Learning)

*Chronic disease RL must learn entirely from historical treatment records. You cannot explore on patients. Batch-Constrained Q-Learning (BCQ) addresses this by restricting the learned policy to only recommend actions that clinicians have actually taken in similar states. This prevents the agent from recommending untested treatment combinations.*

```python
def train_bcq_policy(
    episodes: list,
    num_iterations: int = 15000,
    batch_size: int = 128,
    discount: float = 0.95,
    bcq_threshold: float = 0.3,
    learning_rate: float = 1e-3,
) -> dict:
    """
    Train a Batch-Constrained Q-Learning policy from historical episodes.

    BCQ is particularly appropriate for chronic disease because:
    1. The action space is small (8 treatment options) and discrete
    2. Historical data has good coverage of common transitions
    3. We want to stay close to established clinical practice
    4. The consequences of untested actions unfold over months (no quick recovery)

    The bcq_threshold parameter controls how much the policy can deviate from
    historical behavior:
    - High threshold (0.5+): only recommend actions taken >= 50% of the time
      in similar states. Very conservative.
    - Low threshold (0.1): willing to recommend less common actions if Q-values
      support them. More aggressive.

    For chronic disease, lean conservative. Clinicians have decades of
    experience encoded in their treatment patterns, and the BCQ threshold
    is how you express respect for that experience in code.

    Args:
        episodes: List of episode dicts from build_episode_from_patient_history.
        num_iterations: Training iterations.
        batch_size: Transitions per batch.
        discount: Future reward discount. Lower than acute care (0.95 vs 0.99)
                  because distant outcomes are less certain in chronic disease.
        bcq_threshold: Minimum historical action frequency to consider.
        learning_rate: Step size.

    Returns:
        Dict with Q-table and action frequency table (for BCQ filtering).
    """
    # Flatten episodes into replay buffer
    replay_buffer = []
    for ep in episodes:
        for transition in ep:
            replay_buffer.append(transition)

    if not replay_buffer:
        raise ValueError("Empty replay buffer. Check episode construction.")

    logger.info(
        "Training BCQ: %d transitions, %d iterations, threshold=%.2f",
        len(replay_buffer), num_iterations, bcq_threshold,
    )

    # Tabular implementation (production would use neural networks).
    # Discretize state into bins using key features.
    N_BINS = 8
    q_table = np.zeros((N_BINS ** 3, NUM_ACTIONS))
    # Track action frequencies per state bin (for BCQ constraint)
    action_counts = np.zeros((N_BINS ** 3, NUM_ACTIONS))

    # First pass: count action frequencies in each state region.
    # This tells us what clinicians actually did in similar situations.
    for transition in replay_buffer:
        state = np.array(transition["state"])
        action = transition["action"]
        state_idx = _state_to_index(state, N_BINS)
        action_counts[state_idx, action] += 1

    # Normalize to frequencies
    action_freq = np.zeros_like(action_counts)
    for s in range(action_counts.shape[0]):
        total = action_counts[s].sum()
        if total > 0:
            action_freq[s] = action_counts[s] / total

    # Training loop
    for iteration in range(num_iterations):
        indices = np.random.randint(0, len(replay_buffer), size=batch_size)
        batch = [replay_buffer[i] for i in indices]

        for transition in batch:
            state = np.array(transition["state"])
            action = transition["action"]
            reward = transition["reward"]
            next_state = np.array(transition["next_state"])

            state_idx = _state_to_index(state, N_BINS)
            next_state_idx = _state_to_index(next_state, N_BINS)

            # BCQ constraint: only consider actions with sufficient historical
            # frequency in the next state when computing the target.
            # This prevents bootstrapping from unseen state-action pairs.
            valid_actions = action_freq[next_state_idx] >= bcq_threshold
            if not valid_actions.any():
                # Fallback: use all actions if none meet threshold
                valid_actions = np.ones(NUM_ACTIONS, dtype=bool)

            # Masked max: only consider valid actions for the Bellman target
            masked_q = np.where(valid_actions, q_table[next_state_idx], -np.inf)
            next_q_max = np.max(masked_q)

            # Standard Q-learning update with BCQ-filtered target
            td_target = reward + discount * next_q_max
            q_table[state_idx, action] += learning_rate * (
                td_target - q_table[state_idx, action]
            )

    logger.info("BCQ training complete. Q-table shape: %s", q_table.shape)

    return {
        "q_table": q_table,
        "action_freq": action_freq,
        "n_bins": N_BINS,
        "bcq_threshold": bcq_threshold,
    }


def _state_to_index(state_vector: np.ndarray, n_bins: int) -> int:
    """
    Discretize state to table index using key features:
    - Feature 0: hba1c_current
    - Feature 5: current_treatment_level
    - Feature 12: medication_adherence

    These three features capture the core decision context:
    how controlled is the patient, what are they on, and are they taking it.

    WARNING: This 3-feature discretization discards 13 state features entirely.
    The policy cannot learn patient-specific treatment responses based on renal
    function, cardiovascular risk, age, or comorbidities. In production, use a
    neural network Q-function that takes the full 16-dimensional state vector
    as input. The safety constraint layer partially compensates for this
    limitation but cannot learn nuanced preferences.
    """
    key_features = [state_vector[0], state_vector[5], state_vector[12]]
    bins = np.clip(
        (np.array(key_features) * n_bins).astype(int), 0, n_bins - 1
    )
    return int(bins[0] * n_bins * n_bins + bins[1] * n_bins + bins[2])
```

---

## Step 6: Off-Policy Evaluation

*Before any policy touches a patient, you need to estimate how it would have performed historically. For chronic disease, this is especially important because you can't run a quick A/B test: outcomes take months to observe.*

```python
def evaluate_policy_offline(
    policy: dict,
    test_episodes: list,
    discount: float = 0.95,
) -> dict:
    """
    Evaluate learned policy using concordance metrics against clinician decisions.

    Full off-policy evaluation would use importance sampling or doubly-robust
    estimators to estimate counterfactual policy value. We use concordance
    metrics here for pedagogical clarity: how often does the policy agree
    with clinicians, and what's the treatment intensity profile?

    For chronic disease RL, we care about:
    1. Estimated HbA1c distribution under the learned policy
    2. Estimated hypoglycemia rate
    3. Treatment complexity (are we recommending simpler regimens?)
    4. Agreement rate with clinicians (how often does the policy agree?)

    High agreement with clinicians is actually a good sign for a conservative
    policy. It means the policy learned that clinicians are mostly right,
    and only deviates where the data strongly supports a different choice.

    Args:
        policy: Trained policy dict from train_bcq_policy.
        test_episodes: Held-out patient episodes.
        discount: Reward discount factor.

    Returns:
        Dict with evaluation metrics.
    """
    q_table = policy["q_table"]
    action_freq = policy["action_freq"]
    n_bins = policy["n_bins"]
    threshold = policy["bcq_threshold"]

    agreement_count = 0
    total_decisions = 0
    policy_actions = []
    clinician_actions = []

    for ep in test_episodes:
        for transition in ep:
            state = np.array(transition["state"])
            clinician_action = transition["action"]

            state_idx = _state_to_index(state, n_bins)

            # BCQ-filtered action selection
            valid = action_freq[state_idx] >= threshold
            if not valid.any():
                valid = np.ones(NUM_ACTIONS, dtype=bool)

            masked_q = np.where(valid, q_table[state_idx], -np.inf)
            policy_action = int(np.argmax(masked_q))

            policy_actions.append(policy_action)
            clinician_actions.append(clinician_action)
            total_decisions += 1

            if policy_action == clinician_action:
                agreement_count += 1

    agreement_rate = agreement_count / max(total_decisions, 1)

    # Compare average treatment intensity
    avg_policy_level = np.mean(policy_actions) if policy_actions else 0
    avg_clinician_level = np.mean(clinician_actions) if clinician_actions else 0

    return {
        "agreement_rate": round(agreement_rate, 3),
        "avg_policy_treatment_level": round(avg_policy_level, 2),
        "avg_clinician_treatment_level": round(avg_clinician_level, 2),
        "total_decisions_evaluated": total_decisions,
        "num_test_patients": len(test_episodes),
        "interpretation": (
            "High agreement (>0.7) means the policy learned clinician patterns well. "
            "Lower agreement may indicate the policy found improvement opportunities, "
            "but requires careful validation before trusting the deviations."
        ),
    }
```

---

## Step 7: Clinical Decision Support (Quarterly Visit)

*This is the integration point: at a quarterly diabetes visit, the system constructs the patient's current state, queries the policy, applies safety constraints, and presents a treatment recommendation for the clinician to accept, modify, or reject.*

```python
# AWS clients
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
state_table = dynamodb.Table(DYNAMODB_TABLE)


def fetch_patient_state(patient_id: str) -> dict:
    """
    Retrieve the patient's longitudinal diabetes state from DynamoDB.

    The state table stores the patient's current clinical status, treatment
    history, and relevant comorbidities. Updated at each quarterly visit.
    """
    response = state_table.get_item(Key={"patient_id": patient_id})

    if "Item" not in response:
        logger.warning("No state found for patient %s", patient_id)
        return {}

    item = response["Item"]
    # Convert Decimal to float for numpy
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in item.items()}


def get_policy_recommendation(state_vector: np.ndarray, policy: dict) -> dict:
    """
    Get the RL policy's treatment recommendation.

    In production, this calls a SageMaker endpoint hosting the trained model.
    For this example, we use the local Q-table directly.

    Args:
        state_vector: Normalized state from construct_state_vector.
        policy: Trained policy dict (with q_table and action_freq).

    Returns:
        Dict with recommended action, treatment name, and confidence.
    """
    q_table = policy["q_table"]
    action_freq = policy["action_freq"]
    n_bins = policy["n_bins"]
    threshold = policy["bcq_threshold"]

    state_idx = _state_to_index(state_vector, n_bins)

    # BCQ filtering: only consider historically-supported actions
    valid = action_freq[state_idx] >= threshold
    if not valid.any():
        valid = np.ones(NUM_ACTIONS, dtype=bool)

    masked_q = np.where(valid, q_table[state_idx], -np.inf)
    best_action = int(np.argmax(masked_q))

    # Confidence: gap between best and second-best valid action
    sorted_q = np.sort(masked_q[masked_q > -np.inf])[::-1]
    if len(sorted_q) > 1 and sorted_q[0] != 0:
        confidence = min(1.0, abs(sorted_q[0] - sorted_q[1]) / (abs(sorted_q[0]) + 1e-6))
    else:
        confidence = 0.5

    return {
        "recommended_action": best_action,
        "recommended_treatment": TREATMENT_ACTIONS[best_action]["name"],
        "treatment_description": TREATMENT_ACTIONS[best_action]["desc"],
        "confidence": round(confidence, 3),
        "valid_actions": [
            TREATMENT_ACTIONS[a]["name"] for a in range(NUM_ACTIONS) if valid[a]
        ],
    }
```

---

## Full Pipeline: Quarterly Treatment Recommendation

This assembles all steps into the function called at each quarterly diabetes visit. In production, this would be triggered by the EHR when a clinician opens the patient's chart during a diabetes management visit.

```python
def generate_treatment_recommendation(
    patient_id: str,
    new_hba1c: float,
    visit_data: dict,
    policy: dict,
) -> dict:
    """
    End-to-end pipeline: quarterly visit data in, treatment recommendation out.

    Called when a patient arrives for their quarterly diabetes check. The
    clinician has just received a new HbA1c result and needs to decide
    whether to adjust treatment.

    The clinician always has the final say. This is decision support that
    surfaces the RL policy's suggestion alongside clinical reasoning.

    Args:
        patient_id: Unique patient identifier.
        new_hba1c: New HbA1c measurement (%).
        visit_data: Dict with current visit observations (hypo_events, adherence, etc.)
        policy: Trained policy dict.

    Returns:
        Dict with recommendation, reasoning, and safety information.
    """
    print(f"\n{'='*60}")
    print(f"CHRONIC DM RL: Quarterly visit for {patient_id}")
    print(f"{'='*60}")

    # Step 1: Fetch patient state
    print("\n[1/5] Fetching patient longitudinal state...")
    patient_data = fetch_patient_state(patient_id)
    if not patient_data:
        print("  WARNING: No prior state. Using visit data as baseline.")
        patient_data = {"hba1c_current": new_hba1c, "current_treatment_level": 0}

    # Step 2: Update state with new visit data
    print(f"[2/5] Updating state: new HbA1c = {new_hba1c}%")
    patient_data["hba1c_prev_quarter"] = patient_data.get("hba1c_current", new_hba1c)
    patient_data["hba1c_current"] = new_hba1c
    patient_data["hba1c_trend"] = (
        new_hba1c - patient_data["hba1c_prev_quarter"]
    )
    # Merge visit observations
    patient_data.update({
        "hypo_events_quarter": visit_data.get("hypo_events", 0),
        "medication_adherence": visit_data.get("adherence", 0.8),
        "egfr": visit_data.get("egfr", patient_data.get("egfr", 80)),
        "bmi": visit_data.get("bmi", patient_data.get("bmi", 28)),
    })

    # Step 3: Compute individualized target
    target = compute_individualized_target(patient_data)
    print(f"  Individualized HbA1c target: {target}%")

    # Step 4: Construct state vector and get policy recommendation
    print("[3/5] Constructing state vector and querying policy...")
    state_vector = construct_state_vector(patient_data)
    policy_result = get_policy_recommendation(state_vector, policy)
    print(
        f"  Policy recommends: {policy_result['recommended_treatment']} "
        f"(confidence: {policy_result['confidence']})"
    )

    # Step 5: Apply safety constraints
    print("[4/5] Applying safety constraints...")
    safe_result = apply_safety_constraints(
        policy_result["recommended_action"], patient_data
    )

    if safe_result["constraints_activated"]:
        for constraint in safe_result["constraints_activated"]:
            print(f"  CONSTRAINT: {constraint}")
    else:
        print("  No constraints activated.")

    # Step 6: Package recommendation
    print("[5/5] Packaging recommendation...")
    current_treatment = TREATMENT_ACTIONS[
        int(patient_data.get("current_treatment_level", 0))
    ]["name"]

    recommendation = {
        "patient_id": patient_id,
        "visit_date": time.strftime("%Y-%m-%d"),
        "hba1c": new_hba1c,
        "individualized_target": target,
        "current_treatment": current_treatment,
        "recommended_treatment": safe_result["final_treatment"],
        "treatment_change": safe_result["final_treatment"] != current_treatment,
        "confidence": policy_result["confidence"],
        "reasoning": {
            "hba1c_vs_target": f"{new_hba1c}% vs target {target}%",
            "hba1c_trend": f"{patient_data['hba1c_trend']:+.2f}% per quarter",
            "hypo_events": visit_data.get("hypo_events", 0),
            "adherence": f"{patient_data['medication_adherence']:.0%}",
            "policy_raw_recommendation": policy_result["recommended_treatment"],
            "constraints_activated": safe_result["constraints_activated"],
        },
        "clinician_action": "PENDING",
    }

    change_str = "CHANGE" if recommendation["treatment_change"] else "NO CHANGE"
    print(f"\n  RECOMMENDATION: {safe_result['final_treatment']} ({change_str})")
    print(f"{'='*60}\n")

    return recommendation


# --- Example usage ---
if __name__ == "__main__":
    print("=" * 60)
    print("DEMO: Chronic Disease Treatment Personalization")
    print("=" * 60)
    print("\nThis demo shows the recommendation pipeline structure.")
    print("Without trained policy and AWS resources, we'll use a mock.\n")

    # Create a mock policy for demonstration
    N_BINS = 8
    mock_policy = {
        "q_table": np.random.randn(N_BINS ** 3, NUM_ACTIONS) * 0.1,
        "action_freq": np.ones((N_BINS ** 3, NUM_ACTIONS)) / NUM_ACTIONS,
        "n_bins": N_BINS,
        "bcq_threshold": 0.3,
    }

    # Simulate a patient visit
    mock_visit = {
        "hypo_events": 1,
        "adherence": 0.85,
        "egfr": 72,
        "bmi": 31,
    }

    # Mock the DynamoDB fetch (would fail without real resources)
    original_fetch = fetch_patient_state

    def mock_fetch(patient_id):
        return {
            "hba1c_current": 7.8,
            "current_treatment_level": 1,
            "months_on_current_treatment": 6,
            "age": 62,
            "bmi": 31,
            "egfr": 72,
            "cardiovascular_risk": 1,
            "heart_failure": 0,
            "medication_adherence": 0.85,
            "appointment_adherence": 0.9,
            "comorbidity_count": 3,
            "diabetes_duration_years": 8,
            "severe_hypo_ever": 0,
            "hypo_events_quarter": 1,
        }

    # Patch for demo
    fetch_patient_state_backup = fetch_patient_state

    try:
        # Use mock for demo
        globals()["fetch_patient_state"] = mock_fetch

        result = generate_treatment_recommendation(
            patient_id="DM-2026-08421",
            new_hba1c=8.2,
            visit_data=mock_visit,
            policy=mock_policy,
        )
        print("\nFull recommendation:")
        print(json.dumps(result, indent=2, default=str))

    finally:
        globals()["fetch_patient_state"] = fetch_patient_state_backup
```

---

## Gap to Production

This example demonstrates the mechanics of RL-based chronic disease treatment personalization. Here's the distance between this code and something that would influence a real treatment decision:

**Data pipeline (the real 80% of the work):**
- EHR integration via FHIR R4 APIs to pull longitudinal patient records (labs, medications, diagnoses, vitals) spanning years of care
- Temporal alignment of irregularly-spaced visits into consistent quarterly decision points
- Medication reconciliation: mapping free-text prescriptions to standardized treatment levels (RxNorm, NDC codes)
- Adherence estimation from pharmacy claims (proportion of days covered) rather than self-report
- Handling of treatment gaps, provider changes, and insurance transitions that create missing data
- De-identification pipeline for training data; BAA-covered access for production inference

**Model training:**
- Replace tabular Q-function with a neural network (transformer-based architectures handle variable-length patient histories well)
- Use a proper BCQ or CQL implementation (d3rlpy, or custom PyTorch with proper target networks)
- Train on tens of thousands of patient trajectories spanning 5+ years each
- Stratify by patient subpopulations (newly diagnosed vs. long-standing, with/without complications)
- Hyperparameter tuning: discount factor is especially important for chronic disease (too high and the agent ignores near-term side effects; too low and it ignores long-term complications)

**Validation (the hardest part):**
- Off-policy evaluation with confidence intervals on held-out patient cohorts
- Comparison against ADA guideline-based treatment algorithms on retrospective data
- Subgroup analysis: does the policy work equally well across demographics, comorbidity profiles, and socioeconomic groups?
- Simulation testing with validated glucose-insulin dynamics models (e.g., UVA/Padova simulator for type 1; less standardized for type 2)
- Clinician review: present recommendations to endocrinologists and primary care physicians for face-validity assessment
- IRB approval for any prospective evaluation, even in shadow mode

**Regulatory pathway:**
- FDA Software as a Medical Device (SaMD) classification (likely Class II for treatment recommendations)
- Clinical decision support exemption analysis (does it meet the four criteria for non-device CDS?)
- Real-world evidence generation plan for post-market surveillance
- Predetermined change control plan if the model will be updated with new data

**Deployment:**
- Shadow mode for 12+ months: run alongside standard care, log recommendations, compare against actual clinician decisions without displaying anything
- Clinician education program: endocrinologists and PCPs need to understand what the system does and doesn't do
- Gradual rollout: start with one clinic, one patient population, one disease stage
- Override tracking: every time a clinician rejects the recommendation, log why. This is your feedback signal for model improvement.
- Drift detection: retrain when treatment guidelines change (new drug classes, updated targets) or patient population shifts

**Infrastructure:**
- Error handling and retries for all AWS API calls
- Input validation: reject physiologically impossible values (HbA1c of 25% is a lab error)
- Structured JSON logging with correlation IDs (never log PHI)
- IAM least-privilege: separate roles for training pipeline vs. inference vs. state management
- VPC with VPC endpoints for all AWS services handling PHI
- KMS customer-managed keys for DynamoDB, S3, and SageMaker model artifacts
- DynamoDB point-in-time recovery for the patient state table
- Audit trail: every recommendation, every clinician decision, every override reason

**The honest gap:** This example is maybe 3% of a production system. The RL algorithm is the intellectually interesting part, but chronic disease management adds layers that acute care doesn't have: multi-year validation horizons, competing with well-established clinical guidelines, earning trust from clinicians who've managed diabetes for decades, and navigating a regulatory landscape that hasn't fully figured out how to evaluate adaptive treatment algorithms. Plan for 3-5 years from "working prototype" to "influencing treatment decisions in one clinic."

---

| [← Recipe 15.6: Python Example](chapter15.06-python-example) | [Chapter 15 Index](chapter15-preface) | [Recipe 15.8: Chemotherapy Dose Optimization →](chapter15.08-chemotherapy-dose-optimization) |
|:---|:---:|---:|
