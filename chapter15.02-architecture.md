# Recipe 15.2 Architecture and Implementation: Notification Timing Optimization

*Companion to [Recipe 15.2: Notification Timing Optimization](chapter15.02-notification-timing-optimization). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Personalize for the bandit model.** Personalize supports contextual bandit use cases natively through its "USER_PERSONALIZATION" recipe with exploration. It handles the exploration/exploitation tradeoff, model training, and real-time inference. You feed it interactions (message sends and engagement outcomes), and it learns per-user timing preferences. The key advantage: you don't need to implement LinUCB or Thompson Sampling yourself. Personalize handles the algorithm selection and hyperparameter tuning.

**Amazon SQS for the message queue.** Messages awaiting timing decisions sit in SQS with visibility timeouts aligned to their delivery windows. SQS handles the durability, ordering, and retry semantics. Dead letter queues catch messages that fail to schedule.

**Amazon DynamoDB for the patient context store.** Per-patient feature vectors need sub-millisecond reads at decision time. DynamoDB's key-value access pattern is ideal: look up patient ID, get their feature vector, pass it to the model. TTL on engagement history entries keeps the table from growing unbounded.

**AWS Lambda for orchestration.** The timing decision is a stateless function: read message from queue, fetch patient context, call Personalize for a recommendation, schedule the delivery. Lambda's event-driven model fits perfectly. A scheduled Lambda also handles the "check for messages whose delivery window has arrived" pattern. Lambda security groups should restrict outbound traffic to VPC endpoints only (no internet egress). All AWS service calls in this architecture can be routed through VPC endpoints, eliminating the need for internet access entirely.

**Amazon EventBridge Scheduler for timed delivery.** Once the model selects a send time, EventBridge Scheduler fires at that exact time to trigger the actual delivery. One-time schedules (not recurring) for each message. This replaces the need for a custom scheduler or cron-based polling.

**Amazon Pinpoint for multi-channel delivery.** Pinpoint handles the actual send across SMS, push notification, and email. It also provides delivery and engagement tracking (opens, clicks) that feed back into the reward signal. Note: Pinpoint engagement event delivery to Kinesis is a service-side integration. Pinpoint writes to the Kinesis stream using an IAM role you configure, from the AWS service network. This does not traverse your VPC.

**Amazon SageMaker (alternative to Personalize).** If you need more control over the bandit algorithm (custom reward functions, specific exploration strategies, or offline policy evaluation), SageMaker lets you train and deploy custom models. More work, more flexibility. Use Personalize first; graduate to SageMaker if you hit its limitations.

### Architecture Diagram

```mermaid
flowchart TD
    A[Care Management\nPharmacy\nScheduling] -->|Generate Messages| B[SQS\nMessage Queue]
    B -->|Trigger| C[Lambda\nTiming Decision]
    C -->|Fetch Features| D[DynamoDB\nPatient Context]
    C -->|Get Recommendation| E[Amazon Personalize\nBandit Model]
    E -->|Optimal Time Slot| C
    C -->|Schedule Delivery| F[EventBridge Scheduler]
    F -->|At Scheduled Time| G[Lambda\nMessage Sender]
    G -->|Deliver| H[Amazon Pinpoint\nSMS / Push / Email]
    H -->|Engagement Events| I[Kinesis Data Stream]
    I -->|Process Outcomes| J[Lambda\nReward Calculator]
    J -->|Update Interactions| E
    J -->|Update History| D

    style E fill:#ff9,stroke:#333
    style D fill:#9ff,stroke:#333
    style H fill:#f9f,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Personalize, SQS, DynamoDB, Lambda, EventBridge Scheduler, Pinpoint, Kinesis Data Streams |
| **IAM Permissions** | `personalize:GetRecommendations`, `personalize:PutEvents`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `dynamodb:GetItem`, `dynamodb:PutItem`, `scheduler:CreateSchedule`, `mobiletargeting:SendMessages`, `kinesis:PutRecord`. All permissions should be scoped to specific resource ARNs (queue ARN, table ARN, campaign ARN). The list above shows required actions; production IAM policies must include resource conditions. |
| **BAA** | Required. Patient contact information and engagement patterns are PHI. |
| **Encryption** | DynamoDB: encryption at rest (default). SQS: SSE-KMS with customer-managed key. Kinesis: server-side encryption with customer-managed KMS key. S3 (training data): SSE-KMS. All transit over TLS. Ensure the Kinesis stream's KMS key policy grants the Pinpoint service principal decrypt access. |
| **VPC** | Production: Lambda in VPC with endpoints for DynamoDB (gateway), S3 (gateway), SQS, Kinesis, Personalize, EventBridge Scheduler, Pinpoint (mobiletargeting), KMS, and CloudWatch Logs. Budget approximately $50-60/month for interface endpoints in a 3-AZ deployment. |
| **CloudTrail** | Enabled for all API calls. Pinpoint message events logged separately. |
| **Sample Data** | You need at least 1,000 interactions per message type before the model learns anything useful. Synthetic data works fine for development. |
| **Cost Estimate** | Personalize: ~$0.05/1000 recommendations + training costs. SQS, Lambda, DynamoDB: negligible at typical notification volumes. Pinpoint: per-message fees (SMS ~$0.01, push free, email ~$0.0001). |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Personalize** | Contextual bandit model for timing decisions |
| **Amazon SQS** | Queues messages awaiting timing optimization |
| **Amazon DynamoDB** | Stores per-patient engagement features and preferences |
| **AWS Lambda** | Orchestrates timing decisions and delivery |
| **Amazon EventBridge Scheduler** | Fires delivery at model-selected times |
| **Amazon Pinpoint** | Multi-channel message delivery and engagement tracking |
| **Amazon Kinesis Data Streams** | Streams engagement events for reward computation |
| **AWS KMS** | Encryption key management for PHI data |
| **Amazon CloudWatch** | Monitoring, metrics, alarms |

### Code

#### Walkthrough

**Step 1: Ingest message request.** When an upstream system generates a notification (refill reminder, appointment reminder, educational content), it lands in the message queue with metadata describing the patient, message type, urgency, and deadline. Urgent messages skip the timing optimizer entirely and go straight to delivery. Everything else waits for the timing engine to decide when to send. This decoupling means upstream systems never need to know about the optimization layer. They just produce messages; the timing engine handles the rest.

```pseudocode
FUNCTION handle_message_request(message):
    // Check urgency first. Clinical alerts and time-critical notifications
    // bypass timing optimization entirely.
    IF message.urgency == "IMMEDIATE":
        send_now(message)
        RETURN

    // Check if the message has a deadline that's already too close.
    // If the deadline is within the next decision window, send now rather than risk missing it.
    IF message.deadline AND message.deadline < (now + 1 hour):
        send_now(message)
        RETURN

    // Normal path: queue the message for timing optimization.
    // Include all metadata the timing engine needs to make its decision.
    enqueue message to timing_queue with attributes:
        patient_id    = message.patient_id
        message_type  = message.type          // "refill_reminder", "appointment", "education"
        content_id    = message.content_id    // specific message template
        channel       = message.channel       // "sms", "push", "email"
        deadline      = message.deadline      // latest acceptable send time (null if no deadline)
        created_at    = current timestamp
```

**Step 2: Fetch patient context.** The timing engine needs to know about this specific patient: their historical engagement patterns, preferences, recent message history, and demographic features. This context forms the "state" that the bandit model uses to select the optimal time. The feature vector is pre-computed and stored in a fast lookup store, updated incrementally as new engagement data arrives. Without rich context, the model falls back to population-level timing, which is barely better than the static baseline.

```pseudocode
FUNCTION get_patient_context(patient_id):
    // Retrieve the pre-computed feature vector for this patient.
    // This includes engagement history, preferences, and derived signals.
    record = lookup from patient_context_table where key = patient_id

    IF record is null:
        // New patient with no history. Return default features.
        // The model will use population-level priors until it learns this patient's patterns.
        RETURN default_context with:
            engagement_history = empty
            preferred_hours    = [9, 10, 11, 14, 15, 16]  // population defaults
            fatigue_score      = 0.0
            messages_last_7d   = 0

    // Assemble the context vector the model expects.
    RETURN context with:
        historical_open_rate     = record.open_rate_30d
        historical_action_rate   = record.action_rate_30d
        preferred_hours          = record.top_engagement_hours    // learned from history
        messages_last_7d         = record.recent_message_count
        days_since_last_message  = record.days_since_last_send
        fatigue_score            = record.fatigue_score           // derived: high if many recent ignores
        age_bucket               = record.age_bucket
        chronic_conditions       = record.condition_flags
        channel_preference       = record.preferred_channel
        timezone                 = record.timezone
```

**Step 3: Select optimal send time.** This is the core decision. The bandit model takes the patient context and message features, evaluates each candidate time slot, and returns the slot with the highest expected engagement (plus an exploration bonus for uncertain slots). The model balances what it knows works for this patient with occasional exploration of new time slots. Safety constraints are applied after the model's recommendation: quiet hours are enforced, frequency caps are checked, and the selected time must fall before any message deadline.

```pseudocode
FUNCTION select_send_time(patient_context, message):
    // Build the feature vector combining patient context and message attributes.
    features = combine:
        patient_context                          // who they are, how they've engaged before
        message.type                             // what kind of message this is
        message.channel                          // delivery channel affects timing norms
        current_day_of_week                      // temporal context
        is_holiday_flag                          // engagement patterns shift on holidays

    // Ask the bandit model for a recommended time slot.
    // The model returns a ranked list of time slots with expected reward scores.
    recommendation = call bandit_model.get_recommendation(
        user_id  = patient_context.patient_id,
        context  = features
    )

    selected_slot = recommendation.top_slot     // e.g., "Tuesday 2:30pm"

    // Apply safety constraints. These are hard overrides the model cannot violate.

    // Constraint 1: Quiet hours (9pm - 7am in patient's timezone)
    IF selected_slot falls in quiet_hours(patient_context.timezone):
        selected_slot = next_available_slot_after(7am, recommendation.ranked_slots)

    // Constraint 2: Frequency cap (no more than 2 messages per day to this patient)
    IF patient_context.messages_today >= MAX_DAILY_MESSAGES:
        selected_slot = first_slot_on_next_day(recommendation.ranked_slots)

    // Constraint 3: Deadline enforcement
    IF message.deadline AND selected_slot > message.deadline:
        selected_slot = latest_valid_slot_before(message.deadline, recommendation.ranked_slots)

    // Constraint 4: Channel-specific rules (SMS has TCPA windows)
    IF message.channel == "sms" AND NOT in_tcpa_window(selected_slot, patient_context.timezone):
        selected_slot = next_tcpa_valid_slot(recommendation.ranked_slots)

    RETURN selected_slot
```

**Step 4: Schedule delivery.** Once the optimal time is selected, create a one-time scheduled event that will fire at exactly that time and trigger the message delivery. The schedule includes all the information needed to send the message without re-querying the timing engine. If the scheduled time is "now" (the model thinks the current moment is optimal), deliver immediately rather than creating a schedule with zero delay.

```pseudocode
FUNCTION schedule_delivery(message, selected_slot):
    // If the selected time is within the next 5 minutes, just send now.
    // No point creating a schedule for something that fires immediately.
    IF selected_slot <= (now + 5 minutes):
        send_message(message)
        RETURN

    // Create a one-time schedule that fires at the selected time.
    create_schedule with:
        schedule_time  = selected_slot
        payload        = message                 // everything needed to send
        target         = delivery_lambda_arn     // which function to invoke
        name           = "msg-{message.id}"      // unique, for idempotency
        retry_policy   = retry 3 times with backoff

    // Record the scheduling decision for later analysis and reward attribution.
    log_decision(
        message_id     = message.id,
        patient_id     = message.patient_id,
        selected_time  = selected_slot,
        model_score    = recommendation.score,
        decision_time  = now
    )
```

**Step 5: Track engagement and compute reward.** After delivery, the system monitors for engagement signals: opens, clicks, and most importantly, completed actions (prescription refilled, appointment scheduled, content read to completion). These signals arrive asynchronously, sometimes hours after delivery. The reward calculator maps engagement outcomes to numeric rewards and feeds them back to the bandit model. This closes the learning loop. Without this step, the model never improves.

```pseudocode
FUNCTION process_engagement_event(event):
    // Validate the event before processing. Verify the message_id exists in the
    // decision log and the event timestamp is within the expected reward window
    // (0-48 hours after send). Discard events that fail validation.
    decision = lookup_decision(event.message_id)
    IF decision is null OR event.timestamp > (decision.send_time + 48 hours):
        log_invalid_event(event)
        RETURN

    // Compute reward based on engagement level.
    reward = CASE event.type:
        "action_completed"  -> 1.0    // patient took the desired action (gold standard)
        "link_clicked"      -> 0.5    // engaged meaningfully but didn't complete action
        "message_opened"    -> 0.3    // opened but no further engagement
        "unsubscribed"      -> -0.5   // lost the channel entirely (very bad)
        "spam_reported"     -> -1.0   // worst outcome: regulatory risk + lost channel

    // Feed the reward back to the bandit model for learning.
    record_interaction(
        user_id     = decision.patient_id,
        item_id     = decision.selected_time_slot,
        event_type  = event.type,
        reward      = reward,
        context     = decision.features,
        timestamp   = event.timestamp
    )

    // Update the patient's context store with fresh engagement data.
    update_patient_context(
        patient_id  = decision.patient_id,
        last_engagement_time = event.timestamp,
        engagement_type      = event.type,
        recalculate_rates    = true    // recompute open_rate_30d, action_rate_30d, fatigue_score
    )
```

**Step 6: Handle non-engagement (timeout).** If 48 hours pass with no engagement signal, the message is considered ignored. This is the most common outcome (especially early on) and provides a neutral reward signal. The timeout handler ensures the model learns from silence, not just from positive signals. Without it, the model would only learn from engaged patients and develop a biased view of timing effectiveness.

```pseudocode
FUNCTION handle_engagement_timeout(message_id):
    // 48 hours have passed with no engagement signal.
    // This message was ignored. Record a neutral reward.
    decision = lookup_decision(message_id)

    record_interaction(
        user_id     = decision.patient_id,
        item_id     = decision.selected_time_slot,
        event_type  = "ignored",
        reward      = 0.0,              // neutral: this is the baseline, not a failure
        context     = decision.features,
        timestamp   = now
    )

    // Update fatigue indicators. Consecutive ignores increase fatigue score.
    update_patient_context(
        patient_id           = decision.patient_id,
        increment_ignore_count = true,
        recalculate_fatigue    = true
    )
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter15.02-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample timing decision output:**

```json
{
  "message_id": "msg-20260301-refill-84729",
  "patient_id": "pat-00482",
  "message_type": "refill_reminder",
  "channel": "push",
  "model_decision": {
    "selected_slot": "2026-03-01T18:30:00-05:00",
    "confidence": 0.78,
    "exploration_flag": false,
    "top_3_slots": [
      {"time": "18:30", "score": 0.78},
      {"time": "07:30", "score": 0.71},
      {"time": "12:00", "score": 0.65}
    ]
  },
  "constraints_applied": [],
  "scheduled_delivery": "2026-03-01T18:30:00-05:00"
}
```

**Performance benchmarks (after 90 days of learning):**

| Metric | Population Default | RL-Optimized | Improvement |
|--------|-------------------|--------------|-------------|
| Message open rate | 12% | 19% | +58% |
| Action completion rate | 4% | 7% | +75% |
| Opt-out rate | 0.8% per month | 0.5% per month | -37% |
| Time to action (median) | 6.2 hours | 3.1 hours | -50% |
| Messages per completed action | 25 | 14 | -44% |

**Where it struggles:**

- New patients with no engagement history (cold start). The model falls back to population defaults for the first 5-10 interactions.
- Patients with highly irregular schedules (shift workers, travelers). Patterns are harder to learn when there's no consistent routine.
- Message types with very low base engagement (annual screening reminders). Sparse reward signal means slow learning.
- Patients who engage regardless of timing. The model can't improve on someone who always opens messages within 5 minutes.

---

## Why This Isn't Production-Ready

**Cold start strategy.** The pseudocode shows a simple "use population defaults" fallback for new patients. In production, you'd want a more sophisticated cold start: cluster patients by demographics and use cluster-level timing preferences as priors. A new 65-year-old retiree should inherit the timing patterns of similar retirees, not the global average that's dominated by working-age adults.

**A/B testing infrastructure.** Before deploying the RL model, you need a proper A/B test comparing it against your current static timing. This means holdout groups, statistical significance testing, and guardrail metrics (opt-out rate, complaint rate) that can trigger automatic rollback.

**Model rollback and canary deployment.** New Personalize campaigns should receive a small traffic percentage (5-10%) initially, with automatic rollback if opt-out rate exceeds 2x baseline or engagement drops below 80% of the previous model's performance over a 48-hour window. A bad model can permanently damage patient communication channels through increased opt-outs before anyone notices.

**Timezone handling.** The pseudocode assumes you know the patient's timezone. In practice, you might only have a zip code (which maps to a timezone, usually) or a phone area code (which maps to nothing reliable since number portability). Build robust timezone inference.

**Multi-message coordination.** If a patient has three pending messages, the timing engine needs to space them out, not stack them all at 6:30pm because that's individually optimal for each one. This requires a coordination layer above the per-message bandit (see the multi-message coordination note in the General Architecture section).

---

## Variations and Extensions

**Multi-channel optimization.** Extend the action space from "when to send" to "when and how to send." The model jointly selects timing and channel (SMS at 7am vs. push notification at 6pm vs. email at 9am). Different channels have different engagement patterns, and the optimal channel may vary by time of day and message type.

**Content personalization integration.** Combine timing optimization with content selection. The model doesn't just decide when to send the refill reminder; it decides whether to send the short "time to refill" version or the longer "here's why adherence matters" version. Timing and content interact: a long educational message works better in the evening when patients have time to read; a short action prompt works better during brief phone-check moments.

**Predictive send-ahead.** Instead of waiting for a message to be generated and then optimizing its timing, predict when the patient will next be in a high-engagement state and pre-generate messages to arrive at that moment. This inverts the flow: instead of "message exists, find the best time," it becomes "good time approaching, find a relevant message." Requires tighter integration with message generation systems.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Personalize Developer Guide](https://docs.aws.amazon.com/personalize/latest/dg/what-is-personalize.html)
- [Amazon Personalize Contextual Bandits](https://docs.aws.amazon.com/personalize/latest/dg/native-recipe-bandit.html)
- [Amazon Pinpoint Developer Guide](https://docs.aws.amazon.com/pinpoint/latest/developerguide/welcome.html)
- [Amazon EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`amazon-personalize-samples`](https://github.com/aws-samples/amazon-personalize-samples): End-to-end examples of Personalize campaigns including real-time recommendations and event tracking

**AWS Solutions and Blogs:**
- [Maintaining Personalized Experiences with Machine Learning (AWS Solutions)](https://aws.amazon.com/solutions/implementations/maintaining-personalized-experiences-with-machine-learning/): Deployable solution for real-time personalization pipelines
- [Amazon Personalize Pricing](https://aws.amazon.com/personalize/pricing/)
- [Amazon Pinpoint Pricing](https://aws.amazon.com/pinpoint/pricing/)

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 2-3 weeks | LinUCB bandit with time-of-day features, single message type, single channel. Population-level model (not per-patient). |
| **Production-ready** | 6-8 weeks | Per-patient learning with Personalize, multi-channel support, frequency caps, quiet hours, A/B test framework, monitoring dashboard. |
| **With variations** | 10-12 weeks | Multi-channel joint optimization, content personalization integration, cold-start clustering, fatigue modeling, predictive send-ahead. |

---

---

*← [Main Recipe 15.2](chapter15.02-notification-timing-optimization) · [Python Example](chapter15.02-python-example) · [Chapter Preface](chapter15-preface)*
