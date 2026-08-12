<!-- Removed from chapter07.06-rising-risk-identification.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Rising risk identification is one of those problems that sounds straightforward until you try to measure whether it's working. The detection part is genuinely tractable: compute slopes, set thresholds, flag patients. You can build a working prototype in a few weeks. The hard part is everything that comes after.

The biggest surprise: regression to the mean is a much larger confounder than most teams realize. If you flag the top 5% of "risers" and intervene, roughly half of them would have reverted toward their baseline even without your intervention. That means your apparent 40% success rate might actually be a 20% success rate with 20% regression to the mean. Separating the two requires either a control group (which means deliberately not helping some patients, which is ethically fraught) or statistical methods that most care management teams don't have access to.

The second surprise: the definition of "rising risk" is a policy decision, not a technical one. Different thresholds produce wildly different patient lists. A slope threshold of 0.02/month flags 8% of your population. A threshold of 0.05/month flags 1.5%. Both are "correct" in a technical sense. The right answer depends on your intervention capacity, your cost-effectiveness threshold, and your organizational risk tolerance. Expect to spend more time calibrating thresholds with clinical and operational leadership than building the model.

The thing I'd do differently: start with the intervention capacity constraint and work backward. If your care management team can absorb 50 new patients per month, your model needs to produce approximately 50 high-confidence flags per month. Design the thresholds to match the operational reality, not the other way around.

---

