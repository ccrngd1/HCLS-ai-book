<!-- Removed from chapter15.01-alert-threshold-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of the most satisfying RL applications I've seen in healthcare because the feedback loop is tight and the improvement is immediately visible. Clinicians notice when their pagers stop buzzing every 3 minutes. The before/after is visceral.

But here's what surprised me: the reward function is where all the arguments happen. Engineers want a clean mathematical formulation. Clinicians want nuance. "Well, that alert was technically noise, but I was glad it fired because the patient had been trending that direction." Encoding clinical judgment into a scalar reward is an exercise in lossy compression, and you'll iterate on it more than any other component.

The other surprise: the biggest gains come from the simplest alert types. Heart rate and SpO2 thresholds are easy to optimize because the feedback is unambiguous. Lab value alerts are harder because the response might be "I already knew about that from the morning labs." Medication interaction alerts are the hardest because clinicians dismiss them for legitimate clinical reasons that the system can't observe.

Start with vital sign alerts on a single unit. Get the infrastructure working. Prove the value. Then expand. Trying to optimize all alert types across all units simultaneously is a recipe for a project that never ships.

One more thing: the contextual bandit approach (mentioned in the Technology section) is genuinely sufficient for most deployments. Full RL with multi-step planning is intellectually satisfying but rarely necessary for threshold optimization. The feedback is fast enough that you don't need to reason about delayed consequences. Save the full RL formulation for problems where today's action genuinely affects next month's outcomes (like treatment optimization in Recipe 15.4).

---

