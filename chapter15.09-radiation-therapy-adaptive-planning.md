# Recipe 15.9: Radiation Therapy Adaptive Planning

**Complexity:** Complex · **Phase:** Research/Pilot · **Estimated Cost:** ~$2,000-$8,000/month (training infrastructure)

---

## The Problem

Here's the thing about radiation therapy that most people outside oncology don't realize: the plan you make on day one is wrong by day fifteen.

A patient gets diagnosed with a head and neck tumor. The radiation oncologist and medical physicist spend hours crafting a treatment plan. They use CT imaging to map the tumor volume. They calculate beam angles, intensities, and fractionation schedules that maximize dose to the tumor while sparing critical structures (the spinal cord, the parotid glands, the optic nerves). It's a beautiful optimization problem, and the initial solution is genuinely impressive.

Then the patient starts treatment. Over the course of 30 to 35 daily fractions (sessions), the tumor shrinks. The patient loses weight. The anatomy shifts. The parotid glands change shape. What was a perfectly optimized plan on day one is now delivering suboptimal dose to a target that has moved and changed size, while potentially over-irradiating normal tissue that has shifted into the beam path.

This is called anatomical adaptation, and it's one of the hardest problems in radiation oncology.

The current standard of care handles this crudely. Most centers create one plan and run it for the entire course. Some centers do "adaptive replanning" at fixed intervals (replan at fraction 15, maybe again at fraction 25). Each replan requires a new CT scan, new contouring (a physician manually outlining the tumor and organs on every slice), and new plan optimization. It takes hours of physicist and physician time. It costs the department significant resources. And the timing is arbitrary: replanning at fraction 15 might be too late for a fast-responding tumor or too early for a slow one.

The question that reinforcement learning can help answer: when should you replan, and how should the new plan differ from the current one? Not on a fixed schedule, but based on what's actually happening to this specific patient's anatomy and tumor response.

This is a sequential decision problem. At each fraction, you observe the patient's current state (imaging, dose delivered so far, tumor response). You decide whether to continue the current plan, make minor adjustments, or trigger a full replan. Each decision affects future options and outcomes. The reward is defined over the entire treatment course: maximize tumor control probability while minimizing normal tissue complication probability. Classic RL territory.

---

## The Technology: Reinforcement Learning for Sequential Treatment Decisions

### What Reinforcement Learning Actually Is

Reinforcement learning is a framework for learning optimal sequential decision-making. Unlike supervised learning (where you have labeled examples of correct answers), RL learns from interaction with an environment. An agent observes a state, takes an action, receives a reward, and transitions to a new state. Over many episodes, the agent learns a policy: a mapping from states to actions that maximizes cumulative reward over time.

The key insight that makes RL different from simple optimization: actions have consequences that unfold over time. Choosing to replan today affects what options you have tomorrow. Delivering a higher dose in early fractions constrains what you can safely deliver later. RL handles this temporal credit assignment naturally.

### The MDP Formulation for Radiation Therapy

To apply RL, you need to formalize the problem as a Markov Decision Process (MDP). Here's how that maps to radiation therapy:

**State (what the agent observes at each fraction):**
- Current fraction number (1 through 35, typically)
- Cumulative dose delivered to tumor volume (in Gray)
- Cumulative dose to each organ at risk (OAR)
- Tumor volume change from baseline (from imaging)
- Patient weight change
- Imaging features (CT or CBCT metrics: tumor density, shape, position)
- Current plan parameters (beam angles, intensities)
- Time since last replan

The state space is high-dimensional. A typical formulation might have 50 to 200 continuous features. This is where deep RL (using neural networks as function approximators) becomes necessary.

**Actions (what the agent can decide at each fraction):**
- Continue current plan (no change)
- Adjust beam intensities within tolerance (minor adaptation)
- Trigger full replan (new optimization from current anatomy)
- Modify fractionation (adjust remaining fraction doses)

The action space can be discrete (choose one of these options) or continuous (specify exact intensity adjustments). Discrete is simpler and more interpretable. Continuous gives finer control but is harder to validate.

**Reward (what defines "good"):**
This is where radiation therapy gets genuinely hard to formulate. The reward needs to capture:
- Tumor control probability (TCP): higher cumulative tumor dose is better, up to a point
- Normal tissue complication probability (NTCP): lower OAR doses are better
- Plan quality metrics (homogeneity, conformity)
- Replanning cost (each replan consumes clinical resources)

A typical reward function combines these:

```text
reward = α × TCP_improvement - β × NTCP_increase - γ × replan_cost
```

The weights (α, β, γ) encode clinical priorities. Getting these right requires close collaboration with radiation oncologists. Different tumor sites have different priorities: for brain tumors, sparing the optic nerve might dominate; for lung tumors, sparing healthy lung tissue is paramount.

**Transition dynamics (how the world changes):**
This is the physics and biology. Tumor response to radiation follows stochastic dynamics. Patient anatomy changes are partially predictable (weight loss trends) and partially random (day-to-day positioning variation). The transition model is what makes simulation possible, and simulation is what makes offline RL training feasible.

### Why This Is Hard (The Honest Version)

**Safety constraints are non-negotiable.** You cannot explore freely. A policy that occasionally delivers 80 Gy to the spinal cord (the tolerance is around 50 Gy) is not acceptable, even if it achieves great tumor control on average. RL must operate within hard constraints, not just optimize expected reward. In practice, this requires a two-layer safety architecture. First, during training, penalty-based reward shaping encourages the policy to avoid unsafe actions (making violations rare). Second, at inference time, a hard constraint verification layer blocks any recommendation that would risk exceeding OAR tolerances (making violations impossible to execute). Training-time penalties alone are insufficient: a neural network is a function approximator that can output any action probability, especially in out-of-distribution states. The inference-time safety check is what provides the actual guarantee. Both layers are required. Neither alone is sufficient.

**Offline learning is mandatory.** You cannot run online RL on patients. You cannot randomize treatment decisions to explore the action space. All learning must happen from historical treatment data (retrospective plans, outcomes, imaging) or from simulation. Offline RL has well-known challenges: distribution shift (the learned policy encounters states that weren't in the training data), overestimation bias (the Q-function is optimistic about actions that were rarely taken), and evaluation difficulty (you can't easily test a new policy without deploying it).

**The reward is delayed and noisy.** Treatment outcomes (local control, toxicity) are measured months or years after treatment ends. You need proxy rewards that can be computed during treatment (dose metrics, imaging response) but these are imperfect surrogates for the outcomes you actually care about.

**Physics constraints.** Radiation dose delivery is governed by physics. Not every plan is physically achievable. The RL agent's actions must respect deliverability constraints (machine limitations, beam geometry, dose rate limits). This means the action space is constrained in complex, state-dependent ways.

**Multi-objective optimization.** There's no single "best" plan. There's a Pareto frontier of tradeoffs between tumor control and normal tissue sparing. Different clinicians have different preferences along this frontier. The RL policy needs to either learn a single compromise or be conditioned on preference parameters.

### Offline RL: Learning from Historical Data

Since online experimentation is impossible, the entire approach rests on offline RL (also called batch RL). The idea: learn a policy from a fixed dataset of historical treatment episodes without further interaction with the environment.

The dataset consists of historical patients who received radiation therapy. For each patient, you have:
- Daily imaging (CBCT or CT)
- The plan that was actually delivered
- Any replanning decisions that were made
- Treatment outcomes (tumor control, toxicity, survival)

Offline RL algorithms that work well here include:
- **Conservative Q-Learning (CQL):** Penalizes Q-values for out-of-distribution actions, preventing the policy from being overconfident about actions that were rarely taken in the data
- **Batch-Constrained Q-Learning (BCQ):** Restricts the policy to only select actions that are similar to those in the dataset
- **Decision Transformer:** Frames RL as sequence modeling, conditioning on desired returns to generate action sequences

The choice between these depends on your data volume and the degree to which you want the learned policy to deviate from historical practice.

### Simulation for Data Augmentation

Historical data alone is often insufficient. You might have 500 patients with full imaging and outcome data. That's not enough for deep RL. Simulation bridges the gap.

A radiation therapy simulator models:
- Tumor response dynamics (linear-quadratic model for cell kill, repopulation)
- Anatomical deformation (biomechanical models of tissue change)
- Imaging noise and artifacts
- Dose calculation (simplified but physically plausible)

The simulator generates synthetic treatment episodes that augment the real data. The RL agent trains on a mix of real and simulated episodes. The risk: if the simulator is wrong (and it will be, in some ways), the learned policy may not transfer to real patients. This is the sim-to-real gap, and it's a major research challenge.

**Calibrating the simulator.** You calibrate by fitting simulator parameters (tumor radiosensitivity, repopulation rate, deformation model coefficients) to match observed trajectories in your historical dataset. Validation means comparing simulated treatment trajectories against real ones using distributional metrics (Wasserstein distance on tumor volume curves, KL divergence on dose accumulation distributions). If simulated and real trajectories are statistically distinguishable, your simulator needs work. Periodically re-validate against new real data; if distributional metrics exceed a threshold, trigger recalibration before retraining the policy. The most dangerous failure mode: if the simulator systematically underestimates tumor response variability, the policy will be overconfident about "continue" actions and under-recommend replanning.

### Where the Field Is Now

Radiation therapy adaptive planning with RL is firmly in the research stage. Several academic groups have published proof-of-concept results:
- Retrospective studies showing that RL-derived replanning schedules would have improved outcomes compared to fixed schedules
- Simulation studies demonstrating that RL policies learn clinically reasonable adaptation strategies
- Small prospective pilot studies (single-institution, heavily supervised)

No RL-based adaptive planning system is in routine clinical use as of 2026. The path to clinical deployment requires:
1. Large-scale retrospective validation
2. Prospective clinical trials (likely with clinician override capability)
3. FDA clearance (likely as a clinical decision support tool, not autonomous)
4. Integration with treatment planning systems (TPS) and record-and-verify systems

---

## General Architecture Pattern

The system splits cleanly into two phases: training (offline, periodic) and inference (daily, at the treatment machine).

### Training Phase

```text
[Historical Data] → [Feature Engineering] → [Simulator Calibration] → [Offline RL Training] → [Policy Validation] → [Trained Policy]
```

**Historical Data Collection:** Gather retrospective treatment records including daily imaging, delivered plans, replanning events, and outcomes. This requires integration with the treatment planning system (TPS), the record-and-verify system, and the outcomes database.

**Feature Engineering:** Transform raw imaging and dosimetric data into the state representation. This includes computing tumor volume changes, OAR dose accumulation, and imaging-derived features (radiomics).

**Simulator Calibration:** Build and calibrate a treatment simulator using the historical data. Validate that simulated trajectories are statistically similar to real ones.

**Offline RL Training:** Train the policy using a combination of real historical episodes and simulated episodes. Apply safety constraints during training (constrained MDP formulation).

**Policy Validation:** Evaluate the learned policy on held-out historical patients. Compare decisions and predicted outcomes against actual clinical decisions. Perform sensitivity analysis on reward weights.

### Inference Phase (Clinical Decision Support)

```text
[Daily Imaging] → [State Extraction] → [Policy Query] → [Recommendation + Explanation] → [Clinician Decision] → [Action Execution]
```

**Daily Imaging:** Before each fraction, the patient gets a cone-beam CT (CBCT) or similar imaging for positioning. This imaging also provides the anatomical information needed for state updates.

**State Extraction:** Compute the current state features from the latest imaging, cumulative dose records, and treatment history.

**Policy Query:** Pass the current state to the trained policy. Get back a recommended action (continue, adjust, replan) with associated confidence.

**Recommendation and Explanation:** Present the recommendation to the radiation oncologist with supporting evidence: why this action, what the expected outcome difference is, what the risk of inaction is. Explainability is critical for clinical adoption.

**Clinician Decision:** The physician makes the final call. The system is advisory, not autonomous. Every recommendation can be overridden.

**Action Execution:** If the clinician agrees, the recommended action is executed (plan continues, intensities are adjusted, or a full replan is initiated).

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter15.09-architecture). The Python example is linked from there.

---

## The Honest Take

This is one of the most intellectually satisfying applications of RL I've encountered, and also one of the hardest to deploy responsibly.

The fundamental tension: RL is most valuable when it can discover strategies that humans haven't considered. But in radiation therapy, "strategies humans haven't considered" might mean "strategies that are dangerous in ways we don't understand yet." The conservative offline RL approach (CQL, BCQ) addresses this by staying close to historical practice, but that also limits the potential upside. If the policy can only recommend actions similar to what clinicians already do, what's the point?

The point is timing and personalization. Clinicians already know how to replan. They don't always know the optimal moment to replan for a specific patient. The RL agent's value isn't in discovering novel treatment strategies; it's in identifying the right moment to apply known strategies based on patient-specific trajectory data that's hard for humans to integrate across 30+ fractions.

The acceptance rate problem is real. In pilot studies, clinicians override RL recommendations 30-40% of the time. Some of those overrides are because the clinician has information the model doesn't (patient preference, comorbidities not in the state). Some are because the clinician doesn't trust the model yet. Distinguishing these cases is important for improving the system.

The thing that surprised me most: the reward function design takes longer than the RL algorithm implementation. Getting radiation oncologists to agree on the relative importance of TCP vs. NTCP vs. replanning cost, and to express those preferences as numerical weights, is a months-long conversation. And different oncologists have legitimately different preferences. A single reward function may not capture the diversity of reasonable clinical practice.

Start with the simplest version: binary "replan yes/no" recommendations for a single tumor site (head and neck is the most studied). Get the data pipeline working. Get the clinician interface right. Get the feedback loop running. The RL algorithm is the easy part. Everything around it is hard.

One more thing: patient informed consent for AI-assisted treatment planning is an evolving area. Some institutions require explicit disclosure that an AI system contributes to treatment recommendations, while others consider it part of standard clinical decision support that doesn't require separate consent. Check your institution's IRB and legal requirements early.

---

## Related Recipes

- **Recipe 15.8 (Chemotherapy Dose Optimization):** Similar RL formulation for sequential treatment decisions, but with different dynamics (pharmacokinetics vs. radiation physics) and different safety constraints
- **Recipe 15.6 (Glucose Control in ICU):** Demonstrates constrained RL with continuous state/action spaces and hard safety bounds, applicable pattern for OAR dose constraints
- **Recipe 15.4 (Sepsis Treatment Optimization):** Covers offline RL from observational data in detail, including distribution shift challenges that apply directly here
- **Recipe 9.7 (Radiology AI Triage):** Covers medical imaging feature extraction patterns relevant to the state extraction step
- **Recipe 14.9 (Chemotherapy Scheduling):** Optimization-based approach to treatment scheduling that could serve as a baseline comparison

---

## Tags

`reinforcement-learning` · `radiation-therapy` · `adaptive-planning` · `offline-rl` · `treatment-optimization` · `safety-critical` · `complex` · `research-stage` · `sagemaker` · `step-functions` · `clinical-decision-support` · `hipaa` · `fda`

---

*← [Recipe 15.8: Chemotherapy Dose Optimization](chapter15.08-chemotherapy-dose-optimization) · [Chapter 15 Index](chapter15-preface) · [Next: Recipe 15.10: Hospital Resource Allocation Under Uncertainty →](chapter15.10-hospital-resource-allocation-uncertainty)*
