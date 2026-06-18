# Recipe 4.1: Appointment Reminder Channel Optimization ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.01–0.04 per reminder (channel-dependent)

---

## The Problem

A cardiology practice in the Midwest has a 22% no-show rate. Think about what that number actually means. For every ten scheduled slots, two go empty. The physician sits for fifteen minutes before the MA goes to reception to confirm the patient isn't stuck in traffic. They call. No answer. The slot is written off. At the end of the week, somebody calculates the lost revenue and somebody else calculates the downstream clinical impact on patients who could have been seen in that slot and won't be until the next available opening three weeks out.

The practice has a reminder system. It has had one for years. Here's what it does: at 72 hours before each appointment, it sends every patient a text message. That's it. One channel, one time, every patient.

This fails in at least four distinct ways, simultaneously:

The 74-year-old who uses a flip phone and doesn't understand texts. The message arrives. They don't see it. They call the office the day of the appointment to ask what time it is. Staff time gets spent. Appointment is kept, but barely.

The 34-year-old whose phone number on file is their previous employer's cell because they never updated it after switching jobs. The reminder vanishes into the ether. They genuinely forget the appointment exists. They are the no-show.

The 58-year-old who has opted out of text messages because a previous marketing blast irritated them. The system respects the opt-out and sends nothing. No reminder, no appointment confirmation, no chance to catch a scheduling conflict. They no-show, the system logs it, nobody notices that the root cause was a five-year-old marketing preference.

The 42-year-old who is perfectly reachable by text but for whom 72 hours is the wrong window. They get the text, mean to respond, get busy, and it falls off the mental stack. 24 hours would have landed. 4 hours on the morning of would have landed. 72 hours did not.

None of these are edge cases. All of them are happening to the practice every single day. And the reminder system dutifully reports a 98% delivery rate, because technically the messages all went out. Technical success, operational failure.

The thing that should make you twitch: we have the data to do better on every one of these. The 74-year-old would respond to a phone call. The 34-year-old's email is probably still current. The 58-year-old would respond to a portal message. The 42-year-old needs a 24-hour nudge, not a 72-hour one. The patient interaction log has answers. The reminder system just doesn't know how to ask the right questions.

So the problem statement is deceptively simple: given a scheduled appointment and everything we know about this patient, what's the right channel to reach them on, at the right time? Not the same channel for everyone. Not even the same channel for the same person every time. The right channel, the right message, the right window.

Let's get into how you actually build that.

---

## The Technology: Recommending Under Uncertainty

### The Core Idea

At its heart, channel optimization is a recommendation problem with a small, fixed set of items (the channels) and a very clear success signal (did the patient show up, or at least confirm the appointment). The "items" are tuples: `(channel, time_offset, content_variant)`. SMS at T-72h is a different item from SMS at T-24h. Email at T-168h (a week out) is a different item again. If you include a voice-call channel, you've got one more. Throw in portal push notifications and you might have twenty or thirty distinct item-tuples in your action space.

For each patient, you want to pick the tuple most likely to drive a confirmed, kept appointment. This is a classic resource allocation problem with an important wrinkle: the only way you learn whether a tuple works for a specific patient is to actually use it and see what happens. There is no other data source. There's no Netflix-style catalog of "people like you loved voice calls at 10am." You have to generate the data yourself by making recommendations, observing outcomes, and updating your beliefs.

That property (learning by doing, where each decision generates the signal that improves future decisions) is the defining feature of what machine learning people call the **contextual bandit** problem. It's a simplified cousin of full reinforcement learning. Full RL has sequences of decisions with delayed rewards; contextual bandits just have one decision per episode, with an immediate reward. "Send a reminder, see what happens." One decision, one reward. That's a contextual bandit.

### Three Approaches, Ordered by Sophistication

**Approach 1: Rule-based defaults.** The simplest thing that could possibly work. Encode the explicit patient preferences and a set of clinical rules: if the patient has a stated channel preference, use it. If they've opted out of SMS, never text them. If they're over 70, default to voice. If they haven't logged into the portal in 90 days, don't send portal messages. No learning, no optimization, just well-curated rules.

Rule-based systems are underrated. They're transparent, auditable, and they're what you should have running while you build anything more sophisticated. For many organizations, a well-tuned rules engine gets you most of the way there. The no-show rate drops from 22% to 16%. The next five percentage points of improvement are what the ML approaches fight for.

**Approach 2: Propensity models.** Step up: for each channel, train a classifier that predicts the probability of a successful response conditional on patient features. You end up with one model per channel (a "propensity to confirm given SMS," a "propensity to confirm given email"), and at send time you pick the channel with the highest predicted probability. Gradient-boosted trees work well here. XGBoost, LightGBM, CatBoost, take your pick.

Propensity models are trainable on historical data. If your practice has been sending reminders for a few years, you already have the labels (did the patient confirm? show up?). You feed in patient features (age, demographics, prior engagement history, distance from clinic, visit type, appointment history, portal login recency, prior no-show count) and channel as an input feature, and you learn which channel works for whom.

The limitation: propensity models learn from data you already collected, under whatever policy generated that data. If you've been sending every patient an SMS for three years, your dataset is SMS-heavy. Your model will learn a lot about who responds to SMS and essentially nothing about who would respond to a voice call, because voice calls barely exist in the history. This is a counterfactual problem, and it's a legitimate one. You can partially address it by running controlled experiments to generate data under different channel policies, but you need to design that in.

**Approach 3: Contextual bandits.** The approach that generates its own training data. A contextual bandit explicitly balances exploration (occasionally trying a channel the model isn't sure about, to gather more data) with exploitation (using the channel the model currently believes is best). Over time, it accumulates data across all channels for all patient segments, and the exploration-exploitation trade naturally reduces as confidence grows.

Two bandit algorithms you'll see in production:

- **Epsilon-greedy.** Simplest. With probability `1-ε`, pick the channel with the highest predicted reward. With probability `ε` (typically 5-10%), pick a random channel. The exploration rate is fixed.
- **Thompson sampling.** More principled. For each channel, maintain a probability distribution over its expected reward. At decision time, sample once from each channel's distribution and pick the channel with the highest sample. The natural exploration happens because channels with fewer observations have wider distributions, so they're more likely to produce a high sample and get chosen.

For healthcare appointment reminders, Thompson sampling tends to be the better choice. It explores adaptively (more exploration where you know less, less where you know more) and it's relatively easy to explain to governance: "the system is more confident about channel X for patient cohort Y because it has more data there." The math is surprisingly simple when you use a conjugate prior like Beta-Binomial for binary reward (confirmed / didn't confirm).

### Cold Start, the Healthcare Version

Every recommendation system has a cold-start problem, and healthcare's version is especially sharp. A new patient shows up in your scheduling system. You know their age, phone, email, maybe their insurance. You have zero engagement history. What channel do you pick?

You cannot wait to collect data. Their first appointment is in ten days. You need to reach them now.

The answer is a hierarchical fallback: start with explicit stated preferences (they told you at registration), fall back to demographic cohort priors (how do 35-to-45 year olds with commercial insurance in your market typically respond?), fall back to a conservative system-wide default. As engagement data accumulates for this specific patient, the personal signal dominates the cohort signal within a few interactions. The bandit handles this automatically if you set up the priors correctly; the propensity model handles it if you include cohort features.

A practical note: cohort-level defaults are where fairness concerns enter. If your cohort features include race or neighborhood, you risk encoding disparities in the priors. If your cohort features exclude them, you lose signal. The workable middle ground most places land on: include demographic features for individual personalization with rigorous fairness monitoring, and use neutral proxies (appointment type, distance to clinic, prior engagement) for cohort fallbacks when personal data is thin.

### The Feedback Loop Is the System

Most of the engineering work in this recipe is not the model. It's the feedback loop that feeds the model.

You need to reliably capture:
- **Delivery events.** Did the message actually arrive? Carriers sometimes drop SMS. Email providers sometimes mark you spam. A delivery failure is a different signal from a delivered-but-ignored.
- **Engagement events.** Did the patient open the email, click the confirmation link, tap the push notification? These are intermediate signals that correlate with the ultimate outcome.
- **Response events.** Did they explicitly confirm? Decline? Reschedule?
- **Outcome events.** Did they actually show up? (This is the gold-label reward, but it arrives days after the decision was made.)

Each of these events needs to be joined back to the original reminder decision. Which message, sent on which channel at which time, produced which outcome. The joining key is typically a reminder ID that propagates through your messaging infrastructure and comes back in the delivery receipts. If you can't join events to decisions, you can't learn. This sounds trivial and it is routinely not trivial, especially across multiple messaging providers with different receipt formats.

The reward signal you feed the model is derived from these events. A reasonable definition: `reward = 1 if (patient showed up OR explicitly confirmed within 4 hours of the reminder) else 0`. You'll debate that exact definition forever. Get a working one, track it, and iterate.

### Where This Fits in the Bigger Picture

This recipe is a simple, well-scoped entry point into healthcare personalization. The infrastructure you build here (patient preference store, engagement event pipeline, reward computation, bandit or propensity model serving) is the same infrastructure that future personalization recipes reuse. Recipe 4.2 (Patient Education Content Matching) consumes the preference and engagement data. Recipe 4.5 (Medication Adherence Intervention Targeting) extends the bandit pattern to a more complex action space. Recipe 4.6 (Care Gap Prioritization) reuses the same engagement baselines. Treat this recipe as a capability investment, not just a point solution.

One more framing note: channel optimization sits near the boundary between "operational tooling" and "clinical care." The reminder itself is operational (nobody's treatment decision is being altered by a channel choice), but the information inside a reminder is clinical PHI ("You have a cardiology follow-up on Friday" reveals both a diagnosis area and a care plan). That means the whole pipeline, SMS provider, email provider, everything, needs to be under a BAA. More on that in the [architecture companion](chapter04.01-architecture).

---

## General Architecture Pattern

At a conceptual level, the pipeline has two loops: a decision loop that runs on a schedule to send reminders, and a feedback loop that runs continuously to capture outcomes and update the model.

```text
┌────────────────── DECISION LOOP ───────────────────┐
│                                                    │
│  [Scheduled Appointments]                          │
│           │                                        │
│           ▼                                        │
│  [Scheduler fires at T-N hours before appt]        │
│           │                                        │
│           ▼                                        │
│  [Fetch Patient Features + Preferences]            │
│           │                                        │
│           ▼                                        │
│  [Apply Hard Constraints: consent, opt-outs,       │
│   quiet hours, channel availability]               │
│           │                                        │
│           ▼                                        │
│  [Recommend Channel + Time (bandit or propensity)] │
│           │                                        │
│           ▼                                        │
│  [Compose Reminder (minimum-necessary PHI)]        │
│           │                                        │
│           ▼                                        │
│  [Dispatch via Selected Channel]                   │
│           │                                        │
└───────────┼────────────────────────────────────────┘
            │
            ▼
     [Patient Receives / Responds / Shows Up]
            │
┌───────────┼────────────────────────────────────────┐
│           ▼                                        │
│  [Delivery Receipts + Engagement Events]           │
│           │                                        │
│           ▼                                        │
│  [Join to Original Reminder Decision]              │
│           │                                        │
│           ▼                                        │
│  [Compute Reward]                                  │
│           │                                        │
│           ▼                                        │
│  [Update Model / Bandit State]                     │
│           │                                        │
│           ▼                                        │
│  [Refresh Monitoring: by cohort, by channel]       │
│                                                    │
└──────────────────── FEEDBACK LOOP ─────────────────┘
```

**Scheduled decisions.** Appointments are known in advance, so reminder decisions are not quite real-time. They're scheduled events: at some offset before the appointment, the system evaluates what to send. You typically issue multiple reminders per appointment (a week out, a few days out, the day before, sometimes a same-day nudge), and each one is an independent decision.

**Hard constraints first.** Before any optimization, apply hard rules. If the patient has explicitly opted out of SMS, no amount of "the model thinks SMS is optimal" overrides that. If it's 3 AM in the patient's time zone, no channel is appropriate. If there's no email on file, email isn't in the action space. These constraints filter the candidate set before the model sees it.

**Recommendation engine.** On the filtered candidate set, score each (channel, time) tuple and pick one. Bandit or propensity model, whichever you built. Log the scores and the decision for audit and for future learning.

**Minimum-necessary PHI in content.** The reminder content should contain the minimum PHI necessary to accomplish the purpose. "You have an appointment with Dr. Smith on Friday at 2 PM" reveals provider and timing. "You have your cardiology stress test on Friday" reveals clinical context that may not be necessary for the reminder to work. HIPAA's minimum-necessary standard applies. Different patients will want different levels of detail, and that's a preference you can capture and respect.

**Dispatch and track.** Each message gets a unique reminder ID that travels with it. The messaging provider's delivery receipts carry the ID back so you can join outcomes to decisions. The specific provider doesn't matter for the architecture (and you may have different providers per channel), but the ID propagation is what makes the feedback loop possible.

**Reward computation.** A batch job (hourly, daily, whatever matches your decision cadence) joins engagement events and appointment outcomes to reminders and computes the reward for each. This reward dataset feeds the model update.

**Model update.** For a bandit, this might be continuous or near-continuous (each reward updates the posterior). For a propensity model, it's typically a scheduled retrain (nightly or weekly) on the accumulated data.

**Monitoring by cohort.** Headline metrics (show rate, confirmation rate, cost per confirmed appointment) need to be sliced by patient cohort so you can catch disparities early. If SMS performs great overall but terribly for your over-65 population, the aggregate metric is hiding a problem that's disproportionately hurting one group.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.01-architecture). The Python example is linked from there.

## The Honest Take

The ML is the easy part. Thompson sampling with Beta-Binomial is ten lines of code. The entire rest of this recipe, the consent management, the event plumbing, the idempotency story, the cohort fallbacks, the fairness monitoring, is the hard part. Budget your engineering time accordingly. Teams who budget 80% model, 20% plumbing ship in six months and regret it for years. Teams who budget 20% model, 80% plumbing ship in three months and have something they can actually operate.

The rule-based baseline is better than you think. Before you build a bandit, go run a rules engine for a quarter. Capture stated preferences at registration. Honor them. Send one reminder at T-24h by the patient's preferred channel. Measure the no-show rate. You will likely see a meaningful drop. The bandit's job is to capture the next increment of improvement, and the size of that increment is typically smaller than the size of the rule-based win. Don't skip the rule-based win to chase the bandit.

The most surprising operational issue, at least in the deployments I've read about and advised on, is that the quality of the engagement event stream dominates everything else. Stream records that don't include the reminder ID are worse than useless. SMS carriers that don't reliably return delivery receipts force you to infer "delivered" from "no reply in 30 minutes," and that inference is wrong often enough to corrupt the bandit. Pin down event quality before you build the model. Seriously.

The thing I'd do differently: start with explicit preference capture as the primary lever, and add the bandit later. Most patients, when asked, will tell you their preferred channel. Respect that stated preference. Only fall through to the bandit when preferences are missing, conflicting, or contradicted by actual behavior ("patient said voice but hasn't answered a voice call in two years"). The bandit is for the edges, not the middle. Treating it as the primary decision mechanism makes the system feel less personal than it should, because the patient is telling you what they want and you're asking a model instead of listening.

And the trap worth flagging, because it's the most common failure mode I've seen: conflating engagement with outcome. A reminder that gets opened is not a reminder that worked. A reminder that makes the patient show up is a reminder that worked. If you optimize engagement, you'll pick the channel that's most click-inducing, which may or may not correspond to the channel that drives actual appointment-keeping. The reward definition is the system. Get it right, or build the wrong thing faster.

---

## Related Recipes

- **Recipe 4.2 (Patient Education Content Matching):** Consumes the patient preference and engagement data this recipe produces; demonstrates content-level personalization on top of channel-level personalization.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Extends the bandit pattern from channel selection to intervention-type selection, where the action space is larger and the reward horizon is longer.
- **Recipe 4.6 (Care Gap Prioritization):** Reuses the same engagement-history feature store this recipe populates, applied to a different decision (which care gap to surface to whom).
- **Recipe 11.x (Conversational AI / Virtual Assistants):** The reminder confirmation dialog is a natural touchpoint for light conversational AI (handling reschedule requests, answering FAQ-level questions). The recipes in Chapter 11 build the assistant; this recipe hands it the channel.

---

## Tags

`personalization` · `recommendation` · `contextual-bandit` · `thompson-sampling` · `patient-engagement` · `appointment-reminders` · `multi-channel-messaging` · `sns` · `ses` · `connect` · `dynamodb` · `eventbridge-scheduler` · `lambda` · `simple` · `mvp` · `hipaa`

---

*← [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.2 - Patient Education Content Matching →](chapter04.02-patient-education-content-matching)*
