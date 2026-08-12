<!-- Removed from chapter07.08-disease-progression-modeling.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Disease progression modeling is one of those problems where the concept is intuitive, the clinical value is obvious, and the implementation is humbling. Here's what I've learned:

**The data problem is bigger than the model problem.** You'll spend 70% of your time assembling clean longitudinal data and 30% on the actual modeling. Patient records are fragmented across systems, labs are coded inconsistently, medication histories have gaps, and "lost to follow-up" might mean the patient moved, died, or switched providers. Getting a clean training cohort with reliable outcomes is the hard part.

**Treatment confounding will haunt you.** Your first model will look great on validation metrics and then a nephrologist will point out that it's basically predicting "patients who got aggressive treatment did better," which is obvious and not useful. Accounting for treatment effects properly requires either causal inference expertise or very careful framing of what your model actually predicts ("progression given current treatment continues").

**Clinicians will ask questions your model can't answer.** "What if we add this medication?" "What if the patient loses 20 pounds?" These are counterfactual questions, and a standard predictive model doesn't answer them. You need causal models or simulation-based approaches for "what if" scenarios, and those are a significant step up in complexity.

**Calibration matters more than discrimination.** A model with a C-index of 0.75 that's well-calibrated (when it says 60% risk, 60% of patients actually progress) is more clinically useful than a model with a C-index of 0.80 that's poorly calibrated. Clinicians make decisions based on the probability values, not the ranking.

**The uncertainty bounds are the product, not the point estimate.** I cannot stress this enough. A clinician who sees "42% probability of progression" will treat it as a fact. A clinician who sees "somewhere between 25% and 60% probability" will appropriately factor in their own clinical judgment. Wide uncertainty bounds are honest, not a failure.

**Model drift is real and faster than you'd expect.** Treatment guidelines change. New medications become available. Coding practices shift. A model trained on 2018-2022 data will start degrading by 2024 as the population and treatment landscape evolve. Plan for quarterly retraining from day one.

---

