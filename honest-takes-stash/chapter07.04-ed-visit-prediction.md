<!-- Removed from chapter07.04-ed-visit-prediction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I've learned from watching ED prediction models in the real world:

The model accuracy ceiling is lower than you expect. Published AUROCs of 0.72-0.80 sound mediocre, and they are, compared to something like fraud detection. But the ceiling is low because a large fraction of ED visits are genuinely unpredictable from historical data. You're not predicting car accidents. You're predicting the subset of ED visits that have precursors visible in claims and pharmacy data. That's a smaller set than "all ED visits."

The hardest problem is not technical. It's operational. I've seen models with perfectly good discrimination sit unused because nobody built the workflow that turns a risk score into a care manager's Monday morning list. The model is 20% of the work. The integration with care management platforms, the outreach protocols, the staffing models, and the outcome tracking are the other 80%.

Feature engineering matters more than algorithm choice. I've watched teams spend months tuning XGBoost hyperparameters for a 0.3% AUC improvement, while ignoring the fact that they hadn't incorporated medication adherence data (which would have given them 3-5% improvement). The features are the model. The algorithm is just the container.

Social determinants are the biggest untapped signal and the hardest to operationalize. ZIP code-level deprivation indices add meaningful lift. But patient-level SDOH data (from screenings, community health worker notes, social service referrals) is transformative when available. The problem is that it's available for maybe 10-20% of patients in most health systems.

The "preventable" question never goes away. Stakeholders will always ask "what percent of these ED visits were actually preventable?" And the honest answer is "we don't know for certain, because the counterfactual doesn't exist." You can approximate with studies that categorize ED visits by AHRQ criteria (primary-care-sensitive conditions), but there will always be uncertainty about which specific visits the intervention actually prevented.

---

