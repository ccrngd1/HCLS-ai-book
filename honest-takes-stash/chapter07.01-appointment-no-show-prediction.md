<!-- Removed from chapter07.01-appointment-no-show-prediction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is genuinely one of the easiest ML problems in healthcare to get working. The data is clean, the outcome is binary, the feedback is fast, and the intervention is low-risk. If you're looking for a first ML project to prove value in a health system, this is a strong candidate.

That said, here's what will surprise you:

The model accuracy ceiling is lower than you'd expect. An AUC of 0.80 sounds good until you realize you're still wrong a lot. Human behavior is inherently stochastic. A patient with a 70% predicted no-show probability will still show up 30% of the time. You're not predicting certainty; you're predicting tendencies. Set expectations accordingly with your operations team.

The features matter more than the algorithm. I've seen teams spend weeks tuning XGBoost hyperparameters when the real gain was adding "distance to clinic" or "number of prior no-shows" to the feature set. Start with good features and a simple model. Only add complexity when the simple model plateaus.

The fairness question is real and uncomfortable. No-show models trained on historical data will learn that Medicaid patients, patients from certain zip codes, and patients of certain demographics no-show at higher rates. Those patterns are real, but they reflect systemic access barriers (transportation, childcare, work flexibility), not patient irresponsibility. If you use the model to deprioritize these patients (shorter reminder windows, less outreach), you're reinforcing the disparity. The ethical use is the opposite: direct more resources toward high-risk patients, not fewer. Make sure your action engine reflects this.

The overbooking decision is harder than the prediction. Even with a perfect model, deciding how many patients to overbook requires balancing revenue recovery against patient wait times, provider burnout, and the occasional day when everyone shows up. This is an operations research problem layered on top of the ML problem. Don't let the model make the overbooking decision directly; let it inform a human or a separate optimization system.

Retraining frequency matters more than you'd think. Patient populations shift. New providers join. Telehealth options change behavior. A model trained on 2024 data may not perform well on 2026 appointments. Monthly retraining with a 12-month rolling window is a reasonable default. Monitor AUC weekly and trigger an alert if it drops below your baseline.

---

