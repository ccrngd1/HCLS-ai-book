# Recipe 7.2: Propensity to Pay Scoring

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.001 per prediction

---

## The Problem

Revenue cycle teams in healthcare have a dirty secret: they treat every patient balance the same. A $47 copay from a retired teacher with a perfect payment history gets the same collection sequence as a $3,200 surgical balance from a 24-year-old who has already ignored three statements. Same letters. Same timing. Same phone calls. Same escalation path.

This is wildly inefficient. The average health system writes off 3-5% of net patient revenue as bad debt annually. For a mid-size hospital doing $500M in net patient revenue, that's $15-25M per year in balances that were theoretically collectible but never collected. Some of that is genuinely uncollectible. But a meaningful portion is money that could have been recovered with a different approach: an earlier payment plan offer, a financial counselor conversation at the right moment, or simply prioritizing outreach to the patients most likely to respond.

The problem isn't that revenue cycle teams are lazy. It's that they're overwhelmed. A typical health system has hundreds of thousands of open patient balances at any given time. The collection staff can make maybe 50-100 outreach calls per day. Without a way to prioritize, they work the list alphabetically, or by balance size, or by age of balance. None of these are optimal. The $8,000 balance that's 90 days old might belong to someone who always pays eventually (just slowly). The $200 balance that's 30 days old might belong to someone who will never pay regardless of how many letters you send.

What you actually want is a probability: for each open balance, what's the likelihood that this patient will pay this specific balance within a given timeframe? That probability lets you do three things that transform revenue cycle operations:

1. **Prioritize outreach.** Focus your limited staff time on balances where outreach will actually change the outcome. Don't waste calls on patients who will pay anyway or patients who won't pay regardless.

2. **Offer payment plans early.** For patients with moderate propensity but high balances, an early payment plan offer (before the balance goes to collections) dramatically improves recovery rates. But you can't offer payment plans to everyone; the administrative overhead is too high.

3. **Right-size collection intensity.** Patients with very low propensity to pay may qualify for financial assistance or charity care. Identifying them early saves everyone time and preserves the patient relationship.

This is essentially credit scoring for healthcare. The financial services industry solved this problem decades ago. Healthcare is catching up, and the data is actually richer than what a credit bureau has (you know the patient's clinical context, their insurance situation, their visit history). The challenge is doing it ethically and in compliance with healthcare-specific regulations.

---

## The Technology: Scoring Payment Likelihood from Behavioral Data

### The Credit Scoring Analogy (and Where It Breaks Down)

If you've ever applied for a credit card, you've been scored by a propensity model. FICO scores predict the likelihood that a borrower will default on a loan. They use payment history, credit utilization, length of credit history, types of credit, and recent inquiries. The output is a number (300-850) that lenders use to make decisions.

Propensity to pay in healthcare works on the same principle: use historical behavior to predict future behavior. But there are important differences that make the healthcare version both easier and harder than consumer credit scoring.

**Easier because:** You have richer data. You know the patient's visit history, their insurance coverage, their balance history with your specific organization, whether they've been on payment plans before, and whether they have a pattern of paying after the second statement vs. the fourth. Consumer credit bureaus don't have this level of relationship-specific data.

**Harder because:** The ethical and regulatory landscape is more complex. In consumer lending, it's broadly accepted that creditworthiness determines access to credit. In healthcare, ability to pay should never determine access to care. Your propensity model must be used to optimize collection strategy, not to deny services. This distinction matters for model design, feature selection, and how you communicate results to staff.

**A note on FCRA.** Since this recipe draws an explicit credit scoring analogy, be aware that the Fair Credit Reporting Act may apply to propensity scores depending on how they're used. If scores drive adverse financial decisions (escalating to external collections, denying payment plan eligibility, or changing terms), the scoring system could be considered a "consumer report" under FCRA. The safest posture: use scores for internal prioritization (which staff to call first, when to offer a payment plan) rather than exclusion (denying a patient the option of a payment plan because their score is low). Consult legal counsel before using propensity scores in any workflow that could be characterized as an adverse action. This is one of those areas where the answer is "it depends on your state and your specific use," not "you're fine."

**Harder because:** Healthcare balances are heterogeneous in ways that credit card balances aren't. A $25 copay, a $500 deductible, and a $15,000 surgical balance are fundamentally different collection problems. The patient's propensity to pay a $25 copay tells you almost nothing about their propensity to pay a $15,000 balance. Your model needs to account for balance characteristics, not just patient characteristics.

### Binary Classification with Calibrated Probabilities

Like no-show prediction (Recipe 7.1), propensity to pay is a binary classification problem at its core. Given features about a patient and their balance, predict: will this balance be paid within N days? The output is a probability between 0 and 1.

The critical requirement here is **calibration**. A predicted probability of 0.7 must actually mean that 70% of balances with that score get paid. Why? Because downstream decisions depend on the probability being meaningful, not just the ranking being correct. If you're deciding whether to offer a payment plan (which has administrative cost), you need to know the actual expected recovery, not just that this balance is "more likely to pay than that one."

Logistic regression is a natural starting point because it produces well-calibrated probabilities by default. Gradient-boosted trees (XGBoost, LightGBM) typically have better discrimination (AUC) but worse calibration out of the box. You can fix this with post-hoc calibration (Platt scaling or isotonic regression), but it's an extra step that's easy to forget.

### Features That Drive Payment Behavior

The features that predict healthcare payment behavior fall into four categories:

**Patient payment history.** The strongest predictor, by far. How has this patient handled previous balances with your organization? Did they pay in full? Pay partially? Ignore statements entirely? Respond to the first statement or the fourth? Set up payment plans and complete them, or set up payment plans and default? A patient's track record with your specific organization is more predictive than any external credit data.

**Balance characteristics.** The amount matters enormously. Patients pay small balances at much higher rates than large ones (obvious, but the relationship isn't linear). The type of service matters: patients are more likely to pay for services they chose (elective procedures) than services that happened to them (emergency visits). Whether insurance has already processed the claim matters: a balance that's clearly the patient's responsibility after insurance adjudication gets paid at higher rates than a balance where the patient thinks "insurance should have covered this."

**Insurance and financial context.** Insurance type correlates with payment behavior, but be careful here (more in the ethics section). Self-pay patients have different patterns than patients with high-deductible health plans. Patients who have previously qualified for financial assistance may have changed circumstances. Patients with multiple open balances behave differently than those with a single balance.

**Engagement signals.** Has the patient logged into the patient portal recently? Have they opened the electronic statement? Have they called billing with questions? Have they made partial payments? These engagement signals are highly predictive of eventual payment and are often overlooked. A patient who calls to dispute a charge is actually more likely to eventually pay than one who silently ignores all communication.

### The Outcome Definition Problem

Here's a subtlety that trips up first-time builders: what does "paid" mean?

- Paid in full within 30 days?
- Paid in full within 90 days?
- Paid in full within 365 days?
- Made any payment (even partial) within 90 days?
- Completed a payment plan (even if it took 12 months)?

Each of these is a valid outcome definition, and each produces a different model with different operational implications. A model trained on "paid in full within 30 days" will be very conservative (most balances don't get paid that fast). A model trained on "any payment within 365 days" will be very optimistic.

The right choice depends on your operational question. If you're deciding who to send to external collections at 90 days, train on a 90-day outcome. If you're deciding who to offer a payment plan at 30 days, train on a 30-day outcome. You may need multiple models for different decision points in your collection workflow.

## General Architecture Pattern

```text
[Feature Store] → [Model Training] → [Scoring Service] → [Strategy Engine]
```

**Feature Store.** Pre-computed patient and balance features, updated daily. Pulls from your billing system, patient accounting, EHR demographics, and portal engagement data. Computes derived features: historical payment rate, average days to pay, balance-to-income ratio estimates, engagement recency.

**Model Training.** Periodic retraining on historical balances with known outcomes. The training dataset is balances that are old enough to have a definitive outcome (paid, partially paid, written off, sent to collections). Outputs a calibrated classification model and performance metrics.

**Scoring Service.** Scores new or open balances on a schedule (daily or when a balance status changes). Outputs a probability and the top contributing features. Can run as batch (score all open balances nightly) or real-time (score at the point of service when a new balance is created).

**Strategy Engine.** Maps probabilities to actions. High propensity (>0.8): standard statement cadence, no special intervention needed. Medium propensity (0.4-0.8): proactive payment plan offer, financial counselor outreach. Low propensity (<0.4): early financial assistance screening, charity care evaluation. The thresholds are business decisions, not model decisions.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.02-architecture). The Python example is linked from there.

## The Honest Take

This model is genuinely useful and genuinely straightforward to build. The data exists in every billing system. The outcome is objective. The intervention (changing collection strategy) is low-risk. If you're looking for a first ML project in revenue cycle, this is a strong candidate.

That said, here's what will surprise you:

**The model is less important than the strategy engine.** You can get 80% of the value from a simple heuristic (historical payment rate + balance amount) without any ML at all. The model adds maybe 10-15% lift over that heuristic. The real value comes from actually changing your collection workflow based on the scores. If your collection team ignores the scores and keeps working alphabetically, the model is worthless regardless of its AUC.

**Calibration is harder than discrimination.** Getting a high AUC is easy. Getting well-calibrated probabilities is hard. And calibration is what matters for the strategy engine. If your model says 0.6 but the true rate is 0.45, your payment plan offer threshold is wrong and you're either over-offering (wasting administrative resources) or under-offering (missing recoverable balances).

**The ethical dimension is real.** Your model will learn that certain demographics correlate with lower payment rates. Some of those correlations reflect systemic inequities (income disparities, insurance access gaps), not individual irresponsibility. Using those features to deprioritize outreach to vulnerable populations is ethically problematic and potentially legally risky. Build fairness monitoring from day one, not as an afterthought.

**Feedback loops are tricky.** If you stop contacting low-propensity patients, you'll never know if they would have paid with outreach. Your model's predictions become self-fulfilling. Maintain a small random holdout group that gets standard treatment regardless of score, so you can measure the true counterfactual.

**The 90-day outcome window is a design choice, not a fact.** Different outcome windows produce different models with different operational implications. Talk to your revenue cycle leadership about what decision they're actually trying to make before you pick an outcome definition.

---

## Related Recipes

- **Recipe 7.1 (Appointment No-Show Prediction):** Same architecture pattern (feature store, model training, batch scoring, action engine) applied to a different operational problem. Shares infrastructure and can share the feature engineering pipeline.
- **Recipe 7.3 (Patient Churn / Disenrollment Prediction):** Similar behavioral prediction methodology but focused on retention rather than collection. Overlapping feature sets (engagement signals, visit patterns).
- **Recipe 6.3 (Payer Mix Financial Risk Clustering):** Provides population-level financial risk segmentation that can inform the propensity model's features and the strategy engine's thresholds.
- **Recipe 12.6 (Revenue Cycle Cash Flow Forecasting):** Consumes propensity scores as inputs to forecast expected cash collections at the portfolio level.

---

## Tags

`predictive-analytics` · `risk-scoring` · `revenue-cycle` · `propensity-to-pay` · `binary-classification` · `xgboost` · `sagemaker` · `batch-transform` · `calibration` · `fairness` · `hipaa` · `simple`

---

*← [Recipe 7.1: Appointment No-Show Prediction](chapter07.01-appointment-no-show-prediction) · [Chapter 7 Index](chapter07-preface) · [Next: Recipe 7.3: Patient Churn / Disenrollment Prediction →](chapter07.03-patient-churn-disenrollment-prediction)*
