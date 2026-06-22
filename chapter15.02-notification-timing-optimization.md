# Recipe 15.2: Notification Timing Optimization

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$100-300/month (training + inference infrastructure)

---

## The Problem

Your health system sends 50,000 medication refill reminders a month. Open rate: 12%. Your diabetes management program sends weekly educational content. Engagement rate: 8%. Your care gap outreach team sends colonoscopy screening reminders. Response rate: 4%.

These aren't bad messages. The content is relevant. The patients genuinely need the information. But the messages arrive at 2pm on a Tuesday when the patient is in a meeting, or at 7am on a Saturday when they're sleeping in, or during the exact window when they're commuting and will swipe-dismiss anything that isn't a text from their spouse.

Timing kills engagement in healthcare communications. And the waste isn't just operational (sending messages nobody reads costs money). It's clinical. A medication adherence reminder that arrives at the wrong moment doesn't just get ignored. It trains the patient to ignore future reminders. You're actively conditioning disengagement.

The standard approach is to pick a "best" time based on population averages. Send refill reminders at 9am because that's when open rates are highest across all patients. But population averages hide enormous individual variation. The retired patient who checks their phone at 6am is fundamentally different from the night-shift nurse who's asleep until noon. The parent who has a quiet moment at 8:30pm after the kids are in bed is different from the early-riser who's unreachable after 9pm.

What you actually want is a system that learns, for each patient, when they're most likely to engage with a specific type of health communication. Not just "when do they open messages" but "when do they open messages and actually take the recommended action" (refill the prescription, schedule the appointment, read the educational content).

This is a textbook reinforcement learning problem. The agent observes context (patient, message type, time features), takes an action (send now, or wait), receives a reward (engagement or not), and learns a per-patient policy over time. The exploration cost is low (worst case: a message arrives at a suboptimal time and gets ignored, which is already the baseline). The reward signal is fast and unambiguous. And the improvement potential is substantial: personalized timing typically improves engagement rates by 20-40% over population-level defaults.

---

## The Technology: Reinforcement Learning for Send-Time Optimization

### Why This Is an RL Problem (Not Just Prediction)

You might be thinking: "Can't I just build a classifier that predicts the best send time for each patient?" You could. But there's a subtle problem with the pure prediction approach.

A classifier trained on historical data learns from the times you happened to send messages in the past. If you've always sent refill reminders at 9am, your model learns that 9am is when patients engage with refill reminders. It can't tell you whether 7pm would have been better because you never tried 7pm. This is the exploration problem, and it's exactly what RL is designed to solve.

RL balances exploitation (send at the time you currently believe is best) with exploration (occasionally try different times to discover if something better exists). Over time, it converges on the true optimal timing for each patient, not just the best time among the times you've historically tried.

The second reason this is RL rather than pure prediction: the reward isn't just "did they open it." It's "did they take the desired action within a reasonable window." That action might happen hours after the message was opened. The delayed, sparse reward signal is more naturally handled by RL's credit assignment mechanisms than by a simple classifier.

### The MDP Formulation

**State (what the agent observes at decision time):**

The state captures everything relevant to predicting engagement at this moment:

- Patient features: age bucket, chronic conditions, historical engagement rate, preferred channel (SMS vs. push vs. email), days since last interaction
- Temporal features: day of week, hour of day, holiday flag, days since last message sent to this patient
- Message features: type (refill reminder, appointment reminder, educational content, care gap outreach), urgency level, length
- Contextual signals: weather (yes, really; engagement patterns shift on rainy days), local events, recent app activity if available
- Fatigue indicators: messages sent in last 7 days, messages ignored in last 7 days, current "do not disturb" window if set

**Actions (what the agent decides):**

The simplest formulation: the agent chooses a send-time slot from a discrete set. For example, divide the day into 30-minute windows from 7am to 9pm (28 possible slots), and the agent picks one.

A slightly more sophisticated formulation: the agent decides "send now" or "defer" at each evaluation point. The system evaluates every 30 minutes whether to send a pending message. This naturally handles the case where a message becomes time-sensitive (appointment reminder for tomorrow can't wait indefinitely).

For most implementations, the discrete time-slot approach is simpler and works well. The "send or defer" approach is better when messages have varying urgency and deadlines.

**Reward (the signal that drives learning):**

This is where healthcare notification timing gets interesting. You don't just want opens. You want actions.

- +1.0: Patient takes the desired action within 24 hours (refills prescription, schedules appointment, completes survey)
- +0.3: Patient opens/reads the message but doesn't act
- 0.0: Message is ignored (no open within 48 hours)
- -0.1: Patient unsubscribes or opts out of future messages
- -0.5: Patient explicitly marks message as spam or files a complaint

The asymmetry is intentional. An ignored message is neutral (the baseline). An opt-out is actively harmful because you've lost the channel entirely. A completed action is the gold standard.

**Episode structure:** Each message send is one episode. State observed, action taken (time slot selected), reward received within 48 hours. No multi-step sequential decisions within a single message. This makes it a contextual bandit rather than full RL, which is a significant simplification.

### Contextual Bandits: The Right Abstraction

For notification timing, a contextual bandit is almost always the right formulation rather than full RL. Here's why:

In full RL, the agent reasons about how today's action affects tomorrow's state. "If I send a message today and it gets ignored, does that change the patient's likelihood of engaging tomorrow?" Theoretically yes (message fatigue is real), but modeling that multi-step dynamic adds enormous complexity for marginal benefit.

In a contextual bandit, each decision is independent. The agent observes context, picks an action, gets a reward. Done. The "fatigue" effect is captured implicitly through the state features (messages sent in last 7 days, recent ignore rate) rather than through explicit multi-step planning.

Contextual bandits are:
- Easier to implement (no value function estimation, no temporal difference learning)
- Easier to debug (each decision is self-contained)
- Easier to explain to stakeholders ("the system picks the best time based on patient patterns")
- Faster to converge (fewer parameters, simpler optimization)
- Nearly as effective as full RL for this problem class

The main algorithms you'll encounter:

**LinUCB (Linear Upper Confidence Bound):** Models the expected reward as a linear function of context features. Adds an exploration bonus proportional to uncertainty. Simple, interpretable, works well when the relationship between features and reward is approximately linear. This is the "start here" algorithm.

**Thompson Sampling with neural networks:** Maintains a posterior distribution over reward predictions. Samples from the posterior to select actions. More expressive than LinUCB, handles non-linear patterns, but harder to implement correctly.

**Epsilon-greedy with a learned policy:** Use the best-known time slot most of the time. Randomly explore with probability epsilon. Decrease epsilon over time. The simplest approach, but wastes exploration budget on obviously bad times.

For healthcare notification timing, LinUCB or Thompson Sampling are the standard choices. LinUCB if you want interpretability and simplicity. Thompson Sampling if you want better exploration efficiency and can handle the implementation complexity.

### Offline Learning: Starting Without Exploration

You don't need to explore from scratch. You have historical data: every message you've ever sent, when you sent it, and whether the patient engaged. That's enough to bootstrap a reasonable policy before any online exploration begins.

The offline training process:

1. Collect historical send logs: (patient features, message features, time sent, engagement outcome)
2. Treat the historical send time as the "action taken" and the engagement as the "reward received"
3. Use inverse propensity scoring or doubly-robust estimation to correct for the fact that your historical policy wasn't random (you always sent at 9am, so you have lots of data for 9am and almost none for 7pm)
4. Train the bandit model on this corrected dataset
5. Deploy the learned policy with a small exploration rate to continue improving

The key challenge with offline learning is coverage. If you've never sent messages at 10pm, you have zero data about 10pm engagement. The offline model can't learn about time slots it's never observed. This is why you need some online exploration after deployment, even if the initial policy is trained offline.

### Offline Policy Evaluation (OPE): Knowing Before You Deploy

Before you push a new timing policy to production, you want to answer one question: "Will this new policy actually perform better than what we're doing now?" Offline policy evaluation (OPE) lets you estimate a new policy's performance using only historical data, without sending a single message under the new strategy.

**Why this matters for notification timing:** Your historical policy is almost certainly deterministic (or close to it). You always sent refill reminders at 9am. That means your logged data covers a narrow slice of the action space. OPE must account for this limited coverage honestly, or you'll get dangerously overconfident estimates.

**Doubly-robust estimation** is the standard approach for deterministic (or near-deterministic) historical policies. It combines two estimators:

1. A direct model estimate: train a reward predictor on historical data, then use it to estimate what the new policy would achieve.
2. An inverse propensity score (IPS) correction: re-weight observed outcomes by how likely the new policy would have taken the same action the historical policy took.

The "doubly-robust" property means the estimate is consistent if either the reward model or the propensity model is correctly specified. You don't need both to be perfect, just one. In practice, this gives you much more reliable estimates than either approach alone.

**Coverage limitations are the hard constraint.** If your historical policy never sent messages at 7pm, you have zero data about 7pm outcomes. No amount of statistical cleverness can fill that gap. OPE can only evaluate the new policy on the portions of the action space where historical data exists. If the new policy heavily favors time slots with no historical coverage, your OPE estimate will have wide confidence intervals (or be undefined entirely). This is why the offline training phase should include at least some exploration (even 5-10% random sends) to build coverage across time slots.

**Confidence intervals tell you what you don't know.** A point estimate ("the new policy will achieve 18% open rate") is useless without uncertainty bounds. Compute bootstrap confidence intervals on the doubly-robust estimate. If the 95% confidence interval for the new policy overlaps with the current policy's performance, you don't have enough evidence that the new policy is actually better. Don't deploy on hope.

**Deployment gates tie OPE to your release process.** Set a concrete rule: only deploy a new timing policy if the OPE estimate exceeds the current policy's measured performance by a statistically significant margin (e.g., the lower bound of the 95% CI is above the current policy's mean). This prevents you from shipping models that look good on average but could easily be worse. In practice:

- Compute the doubly-robust estimate with 1,000 bootstrap samples.
- Calculate the 95% confidence interval.
- Compare the lower bound of the CI against the current policy's trailing 30-day engagement rate.
- Only deploy if lower_bound_new > mean_current. Otherwise, collect more data or increase exploration to improve coverage.

This gate should be automated in your retraining pipeline. Every time Personalize produces a new model version or your custom bandit retrains, run OPE against the last 30 days of logged interactions. If the gate passes, promote to canary. If not, keep the current policy and flag for review.

### Safety Constraints for Healthcare Notifications

Even though notification timing is low-stakes compared to clinical RL, there are real constraints:

**Quiet hours.** Never send between 9pm and 7am unless the patient has explicitly opted in to late notifications. This is both a regulatory consideration (TCPA for SMS) and a respect consideration. Hard constraint, not learnable.

**Frequency caps.** No more than N messages per day, M per week, regardless of what the timing model suggests. If the model thinks 3pm Tuesday is optimal for three different messages, you still only send one. Priority ordering handles the rest.

**Channel-specific rules.** SMS has different timing norms than push notifications. Email can arrive anytime (people check it on their schedule). Phone calls have strict TCPA windows. The model should respect channel-specific constraints.

**Urgency overrides.** A medication interaction alert doesn't wait for the "optimal" time. Time-sensitive clinical notifications bypass the timing optimizer entirely. The system needs a clear priority hierarchy.

**Opt-out respect.** If a patient has set "do not disturb" hours in their profile, those are absolute. The model doesn't get to override patient preferences, even if it thinks engagement would be higher.

**Regulatory note:** Systems that optimize timing specifically to increase medication adherence may warrant review under FDA's Clinical Decision Support (CDS) guidance. The line between "informing" a patient and "driving" adherence behavior is genuinely ambiguous here. If your reward signal explicitly targets prescription refill completion, consult your regulatory team on CDS classification.

---

## General Architecture Pattern

The system has four logical components that work together:

```text
[Message Queue] → [Timing Decision Engine] → [Scheduled Delivery] → [Outcome Tracker]
       ↑                    ↑                                              |
       |                    |                                              |
  [Message Sources]    [Patient Context Store]          [Reward Signal] ←──┘
```

**Message Queue:** Upstream systems (care management, pharmacy, scheduling) generate messages that need to be sent. Instead of sending immediately, they're placed in a queue with metadata: patient ID, message type, urgency level, deadline (if any), and content.

**Timing Decision Engine:** The bandit model. For each queued message, it observes the current context (patient features, temporal features, message features), selects the optimal send-time slot, and schedules delivery. For urgent messages, it bypasses optimization and sends immediately.

**Scheduled Delivery:** A scheduler that fires messages at their assigned times. Handles the mechanics of channel selection (SMS, push, email), template rendering, and delivery confirmation.

**Outcome Tracker:** Monitors engagement signals (opens, clicks, actions taken) and maps them back to the original send decision. Computes the reward signal and feeds it back to the model for learning.

**Patient Context Store:** A feature store containing per-patient engagement history, preferences, demographic features, and derived signals (recent fatigue score, preferred time windows from historical data).

The key architectural insight: the timing decision is decoupled from message generation. Upstream systems don't need to know about the optimization. They generate messages; the timing engine decides when to deliver them. This separation of concerns means you can add timing optimization to existing notification infrastructure without rewriting the message generation logic.

**Multi-message coordination:** If a patient has multiple pending messages, the timing engine must serialize decisions for the same patient. Without coordination, parallel processing can schedule three messages to the same "optimal" slot, defeating the frequency cap. Implement a per-patient scheduling lock or deduplication check at schedule creation time: before creating a new schedule, verify no other schedule exists for this patient within a 2-hour window.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter15.02-architecture). The Python example is linked from there.

## The Honest Take

This is one of the most satisfying RL applications in healthcare because you see results fast and the downside risk is genuinely low. Nobody gets hurt if a refill reminder arrives at 3pm instead of 6pm. The worst case is the status quo: the message gets ignored, just like it would have with static timing.

The part that surprised me: the biggest engagement gains don't come from finding the perfect time. They come from avoiding the terrible times. Moving a message from 2pm (patient is always in meetings) to literally any evening hour is a bigger win than optimizing between 6pm and 7pm. The model's first few weeks of learning are mostly about eliminating obviously bad slots, not fine-tuning good ones.

The fatigue modeling matters more than the timing optimization itself. A perfectly timed message to a patient who's received four messages this week is still going to get ignored. The frequency cap and fatigue score do more for engagement than the time-slot selection. If you're going to invest engineering effort somewhere, invest in the fatigue model first and the timing model second.

One thing I'd do differently: start with a simpler model. LinUCB with a handful of features (time of day, day of week, days since last message, historical open rate) gets you 80% of the benefit. The elaborate context features (weather, app activity, chronic conditions) add marginal improvement at significant engineering cost. Ship the simple version, measure the lift, then decide if the complex version is worth building.

Also: the exploration rate matters less than you think. With thousands of patients and daily messages, even 5% exploration generates plenty of learning signal. Don't over-rotate on exploration strategy. The default Thompson Sampling configuration in most bandit platforms is fine.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Closely related; focuses on channel selection rather than timing. The two systems can share patient engagement features.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Consumes timing optimization as a delivery mechanism. The adherence model decides what to send; the timing model decides when.
- **Recipe 15.1 (Alert Threshold Optimization):** Same RL framework (contextual bandits) applied to a different healthcare problem. Shares architectural patterns for reward tracking and safety constraints.
- **Recipe 7.1 (Appointment No-Show Prediction):** No-show predictions can feed into the timing model as context (patients predicted to no-show might benefit from differently-timed reminders).

---

## Tags

`reinforcement-learning` · `contextual-bandits` · `notification-timing` · `patient-engagement` · `personalize` · `pinpoint` · `personalization` · `simple` · `mvp` · `lambda` · `dynamodb` · `hipaa`

---

*← [Recipe 15.1: Alert Threshold Optimization](chapter15.01-alert-threshold-optimization) · [Chapter 15 Index](chapter15-preface) · [Next: Recipe 15.3: Clinical Trial Adaptive Randomization →](chapter15.03-clinical-trial-adaptive-randomization)*
