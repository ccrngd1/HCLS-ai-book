<!-- Removed from chapter15.02-notification-timing-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of the most satisfying RL applications in healthcare because you see results fast and the downside risk is genuinely low. Nobody gets hurt if a refill reminder arrives at 3pm instead of 6pm. The worst case is the status quo: the message gets ignored, just like it would have with static timing.

The part that surprised me: the biggest engagement gains don't come from finding the perfect time. They come from avoiding the terrible times. Moving a message from 2pm (patient is always in meetings) to literally any evening hour is a bigger win than optimizing between 6pm and 7pm. The model's first few weeks of learning are mostly about eliminating obviously bad slots, not fine-tuning good ones.

The fatigue modeling matters more than the timing optimization itself. A perfectly timed message to a patient who's received four messages this week is still going to get ignored. The frequency cap and fatigue score do more for engagement than the time-slot selection. If you're going to invest engineering effort somewhere, invest in the fatigue model first and the timing model second.

One thing I'd do differently: start with a simpler model. LinUCB with a handful of features (time of day, day of week, days since last message, historical open rate) gets you 80% of the benefit. The elaborate context features (weather, app activity, chronic conditions) add marginal improvement at significant engineering cost. Ship the simple version, measure the lift, then decide if the complex version is worth building.

Also: the exploration rate matters less than you think. With thousands of patients and daily messages, even 5% exploration generates plenty of learning signal. Don't over-rotate on exploration strategy. The default Thompson Sampling configuration in most bandit platforms is fine.

---

