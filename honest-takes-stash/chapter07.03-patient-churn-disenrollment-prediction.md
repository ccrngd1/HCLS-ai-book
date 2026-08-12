<!-- Removed from chapter07.03-patient-churn-disenrollment-prediction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

I'll be direct about what surprised me building these systems.

The model is the easy part. Seriously. You can get a decent XGBoost model trained in an afternoon. The feature engineering takes weeks. Getting clean, timely data from six different source systems, each with its own update cadence, data quality issues, and access controls? That's the real project. Plan accordingly.

Calibration is non-negotiable but often skipped. I've seen teams deploy models where a "0.8 probability" actually corresponds to 30% churn. The business makes decisions based on those numbers. If your probabilities aren't calibrated, your intervention thresholds are meaningless and your ROI calculations are fiction.

The intervention matters more than the model. A perfect churn prediction with no retention program is just an expensive way to watch members leave. Before you build the model, make sure you have answers to: "What will we do differently for high-risk members?" If the answer is "nothing," save your money.

Seasonality will fool you. Churn in healthcare is heavily seasonal (open enrollment periods, annual renewal cycles). A model trained on January-March data and deployed in October will underperform because the feature distributions shift. Train on full annual cycles and include time-of-year features.

The ethical dimension is real. Churn models can inadvertently encode discrimination. If members in underserved zip codes have worse network adequacy and higher churn, your model learns "zip code predicts churn." The intervention might then focus retention efforts on members who are already well-served while ignoring the root cause (network gaps) for those who aren't. Monitor your model's predictions across demographic groups and ensure interventions address root causes, not just symptoms. Document your model's fairness characteristics in a model card: which features are included, which were excluded and why, and how predictions distribute across demographic groups. CMS and state regulators are increasingly scrutinizing algorithmic decision-making in health plans. Having a documented fairness analysis before you're asked for one is significantly less painful than producing one under regulatory pressure.

---

