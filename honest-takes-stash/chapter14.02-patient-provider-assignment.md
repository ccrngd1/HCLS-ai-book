<!-- Removed from chapter14.02-patient-provider-assignment.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The optimization part is the easy part. Seriously. Formulating the integer program, running the solver, getting an optimal solution: that's a weekend project for anyone who's taken an OR class. The hard parts are everything around it.

**Getting the weights right is a political problem, not a technical one.** Your medical director wants complexity matching weighted at 50%. Your operations VP wants panel balance at 50%. Your patient experience officer wants language concordance at 50%. They can't all be 50%. The optimization framework forces this conversation into the open, which is valuable but uncomfortable. Expect the first three months to be mostly weight-tuning based on stakeholder feedback on the assignments produced.

**The scoring function encodes bias whether you intend it or not.** If language concordance is weighted heavily and your Mandarin-speaking providers happen to be your most junior, you'll systematically assign Mandarin-speaking patients to junior providers. That might be fine (language concordance genuinely matters for outcomes) or it might perpetuate a disparity you'd rather address by hiring more senior Mandarin-speaking providers.

### Fairness and Bias Monitoring

This deserves its own subsection because it's easy to ship an optimizer that "works" while silently creating demographic imbalances. Three concrete steps:

**Log everything.** Every assignment record should include patient demographics (race, ethnicity, preferred language, age, gender) alongside the provider assigned and the match score. You can't detect what you don't measure.

**Run periodic statistical tests.** Monthly or quarterly, pull assignment logs and run chi-square tests comparing each provider's assigned patient demographics against the practice's overall patient demographics. If Dr. Chen's new assignments are 80% Mandarin-speaking patients while the practice is 15% Mandarin-speaking, that's a statistically significant deviation. It might be intentional (language concordance is working) or it might indicate the optimizer is funneling patients in ways that create workload or complexity imbalances across demographic lines.

**Alert on deviation.** Set thresholds for demographic concentration. If any provider's panel demographics (by race, ethnicity, or language) deviate from the practice average by more than two standard deviations, fire an alert to the panel management team. They decide whether it's acceptable (language matching is doing its job) or needs weight adjustment. The optimizer makes these patterns visible; humans decide what to do about them.

**Providers will override your optimizer.** And that's fine. The optimizer suggests; humans decide. But track the override rate. If it's above 20%, your scoring function doesn't match clinical judgment and needs recalibration. If it's below 5%, you might be able to auto-approve low-risk assignments (healthy patients to providers with ample capacity) and only route complex cases to human review.

**The incremental case is where you'll spend most of your engineering time.** The batch optimizer runs weekly or on-demand. The incremental assigner runs every time a new patient calls. It needs sub-second latency, which means you can't spin up a batch compute job for each patient. Pre-compute provider scores and cache them. Update the cache when panel counts change. The architecture for incremental assignment is fundamentally different from batch, even though the scoring logic is shared.

---

