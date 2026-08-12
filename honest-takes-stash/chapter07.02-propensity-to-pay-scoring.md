<!-- Removed from chapter07.02-propensity-to-pay-scoring.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This model is genuinely useful and genuinely straightforward to build. The data exists in every billing system. The outcome is objective. The intervention (changing collection strategy) is low-risk. If you're looking for a first ML project in revenue cycle, this is a strong candidate.

That said, here's what will surprise you:

**The model is less important than the strategy engine.** You can get 80% of the value from a simple heuristic (historical payment rate + balance amount) without any ML at all. The model adds maybe 10-15% lift over that heuristic. The real value comes from actually changing your collection workflow based on the scores. If your collection team ignores the scores and keeps working alphabetically, the model is worthless regardless of its AUC.

**Calibration is harder than discrimination.** Getting a high AUC is easy. Getting well-calibrated probabilities is hard. And calibration is what matters for the strategy engine. If your model says 0.6 but the true rate is 0.45, your payment plan offer threshold is wrong and you're either over-offering (wasting administrative resources) or under-offering (missing recoverable balances).

**The ethical dimension is real.** Your model will learn that certain demographics correlate with lower payment rates. Some of those correlations reflect systemic inequities (income disparities, insurance access gaps), not individual irresponsibility. Using those features to deprioritize outreach to vulnerable populations is ethically problematic and potentially legally risky. Build fairness monitoring from day one, not as an afterthought.

**Feedback loops are tricky.** If you stop contacting low-propensity patients, you'll never know if they would have paid with outreach. Your model's predictions become self-fulfilling. Maintain a small random holdout group that gets standard treatment regardless of score, so you can measure the true counterfactual.

**The 90-day outcome window is a design choice, not a fact.** Different outcome windows produce different models with different operational implications. Talk to your revenue cycle leadership about what decision they're actually trying to make before you pick an outcome definition.

---

