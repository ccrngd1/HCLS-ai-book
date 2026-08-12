<!-- Removed from chapter15.06-glucose-control-icu.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I've learned from working on this class of problem: the RL formulation is the easy part. Getting the data pipeline right is 70% of the work.

EHR data for glucose control is a mess. Glucose measurements come from different sources (point-of-care meters, arterial blood gas analyzers, continuous glucose monitors) with different accuracies and different timestamps. Insulin orders don't always match insulin administrations (a nurse might hold a dose if the patient is eating). Nutrition data is often incomplete or delayed in charting. You'll spend months cleaning and aligning temporal data before you can train anything.

The reward function is where clinical and ML expertise must collaborate. I've seen teams spend weeks tuning the reward shape, only to realize that their hypoglycemia penalty wasn't steep enough and the policy was trading a 2% increase in time-in-range for a 1% increase in hypoglycemia. That's a terrible trade clinically, but the numbers looked good on the aggregate metric. Always report hypoglycemia rates separately from time-in-range. Never let them get averaged into a single score.

The biggest surprise: the safety constraint layer often matters more than the RL policy itself. A simple PID controller with good safety constraints can outperform a sophisticated RL policy with weak constraints. The constraints encode decades of clinical knowledge about what's dangerous. The RL policy adds value at the margins (better personalization, better anticipation of trends), but the constraints keep patients alive.

Clinician trust is the deployment bottleneck, not model accuracy. Even if your OPE shows a 15% improvement in time-in-range, ICU nurses and physicians won't follow recommendations from a system they don't understand. Plan for extensive education, transparent reasoning displays, and a long period of "shadow mode" where the system makes recommendations that are logged but not displayed.

---

