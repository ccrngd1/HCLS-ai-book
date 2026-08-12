<!-- Removed from chapter08.01-chief-complaint-classification.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is genuinely one of the most satisfying NLP problems to solve in healthcare because the feedback loop is so tight. You build the classifier, deploy it, and within a day you can see whether it's routing correctly. The wins are immediate and visible: fewer misroutes, faster triage, cleaner analytics.

The abbreviation map is where you'll spend more time than you expect. Every institution has its own dialect. "SOB" is universal, but you'll discover abbreviations you've never seen before in the first week of reviewing low-confidence predictions. Build tooling to surface unrecognized tokens from the preprocessing step. Treat the abbreviation map as a living dictionary that grows from real usage.

The confidence threshold is your primary operational lever. Start at 85% and measure your auto-route accuracy for two weeks. If accuracy is above 95% for auto-routed predictions, you can safely lower the threshold. If it's below 90%, raise it. The right threshold depends on the downstream cost of misclassification at your institution. Misrouting a cardiac chest pain to a non-urgent track is worse than sending a "mild headache" to human review unnecessarily.

The thing that surprised me: training data quality matters far more than model sophistication. A simple logistic regression trained on 50,000 clean, correctly-labeled examples will outperform a fancy transformer trained on 10,000 noisy labels where half the historical routings were themselves incorrect. Spend your time on data quality, not model architecture.

Retraining cadence matters too. Quarterly retraining picks up vocabulary drift (new abbreviations, changing documentation patterns from staff turnover). Monthly is better if you have the automation. The model should always be learning from its own corrections.

---

