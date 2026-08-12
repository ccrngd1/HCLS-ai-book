<!-- Removed from chapter04.01-appointment-reminder-channel-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The ML is the easy part. Thompson sampling with Beta-Binomial is ten lines of code. The entire rest of this recipe, the consent management, the event plumbing, the idempotency story, the cohort fallbacks, the fairness monitoring, is the hard part. Budget your engineering time accordingly. Teams who budget 80% model, 20% plumbing ship in six months and regret it for years. Teams who budget 20% model, 80% plumbing ship in three months and have something they can actually operate.

The rule-based baseline is better than you think. Before you build a bandit, go run a rules engine for a quarter. Capture stated preferences at registration. Honor them. Send one reminder at T-24h by the patient's preferred channel. Measure the no-show rate. You will likely see a meaningful drop. The bandit's job is to capture the next increment of improvement, and the size of that increment is typically smaller than the size of the rule-based win. Don't skip the rule-based win to chase the bandit.

The most surprising operational issue, at least in the deployments I've read about and advised on, is that the quality of the engagement event stream dominates everything else. Stream records that don't include the reminder ID are worse than useless. SMS carriers that don't reliably return delivery receipts force you to infer "delivered" from "no reply in 30 minutes," and that inference is wrong often enough to corrupt the bandit. Pin down event quality before you build the model. Seriously.

The thing I'd do differently: start with explicit preference capture as the primary lever, and add the bandit later. Most patients, when asked, will tell you their preferred channel. Respect that stated preference. Only fall through to the bandit when preferences are missing, conflicting, or contradicted by actual behavior ("patient said voice but hasn't answered a voice call in two years"). The bandit is for the edges, not the middle. Treating it as the primary decision mechanism makes the system feel less personal than it should, because the patient is telling you what they want and you're asking a model instead of listening.

And the trap worth flagging, because it's the most common failure mode I've seen: conflating engagement with outcome. A reminder that gets opened is not a reminder that worked. A reminder that makes the patient show up is a reminder that worked. If you optimize engagement, you'll pick the channel that's most click-inducing, which may or may not correspond to the channel that drives actual appointment-keeping. The reward definition is the system. Get it right, or build the wrong thing faster.

---

