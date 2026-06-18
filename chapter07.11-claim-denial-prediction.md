# Recipe 7.11: Claim Denial and Prior-Auth Determination Prediction

**Complexity:** Medium-Complex · **Phase:** MVP · **Estimated Cost:** ~$0.002 per prediction

---

## The Problem

Here's a number that should make every revenue cycle leader lose sleep: the average health system's initial claim denial rate sits between 10% and 15%. That sounds manageable until you do the math. A mid-size hospital submitting 500,000 claims per year at a 12% denial rate means 60,000 claims bouncing back. Each denied claim costs $25 to $118 to rework (depending on complexity and how many times it ping-pongs), and about 60% of denied claims are never resubmitted at all. That's revenue evaporating because the rework process is too expensive or too slow to justify the effort.

The industry collectively writes off billions annually to denials that were preventable. Not "theoretically preventable in a perfect world" preventable. Preventable in the sense that a human reviewer with enough time and context would have caught the issue before submission. The problem isn't knowledge; it's volume. A coder reviewing 80 claims per day cannot cross-reference every diagnosis-procedure pair against every payer's specific coverage rules against every modifier requirement against the patient's specific benefit plan.

What if you could predict, before a claim leaves your building, whether a payer is likely to deny it? Not as a vague "this claim seems risky" flag, but as a specific probability with an explanation: "This claim has a 73% chance of denial because Payer X denies CPT 27447 without prior authorization when the patient is under 60, and this patient is 54 with no PA on file."

That prediction lets you do two distinct things. First, you can fix the claim before submission (add the missing documentation, correct the modifier, obtain the PA). Second, you can prioritize your denial management team's workload: when denials do come back, work the ones with the highest dollar value and the highest likelihood of successful appeal first.

There's an important framing distinction here. This recipe covers the provider-side problem: predicting how a payer will adjudicate your claim. A provider organization building this model is essentially reverse-engineering the payer's decision logic from historical outcomes. That's different from a payer building its own adjudication support model (which would have access to internal coverage rules, medical policies, and utilization management criteria directly). Both are valid ML applications, but the data landscape, feature availability, and ethical considerations differ significantly. We'll focus on the provider perspective because that's where the pain is loudest and the data access constraints are most interesting.

For prior-authorization predictions specifically, the value proposition is even clearer. If you can predict that a PA request is likely to be denied before you submit it, you can strengthen the clinical documentation, escalate to peer-to-peer review proactively, or route the patient to an alternative covered pathway. The typical PA determination timeline is 3-5 business days for standard requests (longer for complex cases), and every day of delay is a day the patient waits for care.

---

## The Technology: Supervised Classification on Tabular Claims Data

### This Is Classification, Not Clustering

Let's be precise about what we're building. This is a supervised classification problem. The outcome variable is a known categorical label: paid, denied, or (for prior-auth) approved, denied, or pended. You have abundant labeled historical data because every claim your organization has ever submitted has a final adjudication status. Every PA request has a determination.

That's the ideal setup for supervised learning. You have input features (everything you know about the claim at submission time), a target variable (what actually happened), and hundreds of thousands of labeled examples to learn from.

Unsupervised methods like clustering are complementary but not the core predictor. You might cluster denial reasons to discover patterns ("these 12 denial codes all map to the same underlying documentation issue"), or use clustering for feature discovery ("claims from providers in this behavioral cluster get denied at higher rates"). Those are useful upstream steps for feature engineering. But the prediction itself is a supervised classification task with a clear ground truth label.

### Gradient-Boosted Trees: The Workhorse

For tabular data with mixed feature types (categorical codes, numerical amounts, binary flags, interaction features), gradient-boosted tree ensembles (XGBoost, LightGBM, CatBoost) are the default choice for good reason. They handle the feature landscape of claims data naturally:

**High-cardinality categoricals.** There are roughly 10,000 CPT codes, 70,000 ICD-10 codes, and hundreds of payer-plan combinations. Boosted trees handle categorical splits natively (LightGBM, CatBoost) or work well with target encoding (XGBoost). Deep learning approaches would need embedding layers and significantly more training data to match performance on this feature type.

**Non-linear interactions.** The denial probability for CPT 27447 (knee replacement) isn't just about the procedure code; it's about the procedure code crossed with the payer, crossed with whether prior auth was obtained, crossed with the patient's age. Boosted trees discover these interactions automatically through their recursive splitting. You don't need to hand-engineer every two-way and three-way feature combination.

**Missing data tolerance.** Real claims data is messy. Not every claim has every field populated. Tree models handle missing values natively (they learn which direction to send missing values at each split). This is a practical advantage over logistic regression, which requires imputation decisions for every missing feature.

**Baseline models for comparison.** Always start with logistic regression as a baseline. It's fast, interpretable, and gives you a floor to beat. If logistic regression with a few well-chosen features gets you to 0.78 AUC, you know the signal is there. Random forests are a natural second baseline: they give you feature importance for free and are harder to overfit than a single gradient-boosted model.

In practice, most production deployments use a tiered approach: payer-specific models for your top 5-10 payers by volume (where you have enough training data per payer), with a global model as fallback for low-volume payers. Start with a global model for the MVP, but plan the transition to payer-specific models before production launch. The signal difference is significant: what matters for UnitedHealthcare is very different from what matters for Medicare.

Why not deep learning? For structured tabular data with under a million rows, gradient-boosted trees consistently match or beat neural networks in benchmarks. The claims data landscape (high-cardinality categoricals, sparse interaction effects, moderate dataset sizes) is exactly where tree models shine. You'd consider deep learning if you were incorporating unstructured data (clinical notes, faxed documents) into the prediction, but for the structured claim fields alone, stick with trees.

### Explainability Is Not Optional

Here's where claim denial prediction differs from, say, ad click prediction. Every flagged claim needs a defensible reason. When your model says "this claim has a 78% denial probability," the coder or biller reviewing it needs to know why. "The model says so" is not actionable. "The model flagged this because Payer X denies 67% of claims with this diagnosis-procedure combination when the place of service is outpatient, and your historical denial rate with this payer for similar claims is 71%" is actionable.

SHAP (SHapley Additive exPlanations) values give you exactly this. For each prediction, SHAP decomposes the output into per-feature contributions. You can say: "These three features pushed the denial probability up by 0.35, and these two features pushed it down by 0.12." The biller can then look at the top risk factors and decide which ones are fixable before submission.

This isn't just nice-to-have. It's operationally essential. A model without explanations is a model nobody trusts, and a model nobody trusts is a model nobody uses.

### The Feature Space

The features that predict claim determinations fall into several categories:

**Procedure and diagnosis codes.** The CPT/HCPCS procedure code, ICD-10 diagnosis codes (primary and secondary), and critically, the diagnosis-procedure pairs. A diagnosis code alone might be perfectly fine. A procedure code alone might be perfectly fine. But the combination might violate medical necessity criteria for a specific payer. These pairs (and triples) are where most of the predictive signal lives.

**Payer-specific context.** Payer ID, specific plan/product, the payer's historical denial rate for this procedure code, and whether payer-specific rules require prior authorization, specific modifiers, or documentation. Different payers have wildly different denial patterns for the same procedure.

**Provider context.** Provider type (physician, NP, facility), provider specialty, the specific provider's historical denial rate (some providers consistently code in ways that trigger denials), and the rendering vs. billing provider relationship.

**Claim structural features.** Place of service, modifiers (26, TC, 59, etc.), units billed, claim amount, number of line items, whether this is an initial submission or resubmission, and the time elapsed since date of service.

**Prior-authorization status.** Whether PA was required, whether it was obtained, whether it's still active (PAs expire), and the PA determination for the specific service.

**Patient context.** Patient age, coverage type (commercial, Medicare, Medicaid), whether the patient has a deductible remaining, coordination of benefits status, and whether the patient has had similar claims denied previously.

**Modifier and bundling signals.** Whether the procedure has common unbundling issues, whether required modifiers are present, whether the claim contains procedure combinations known to trigger NCCI edits.

### Three Prediction Points in the Claim Lifecycle

You can deploy denial prediction at three distinct points, each with different feature availability and different intervention options:

**Pre-visit (eligibility and PA risk).** Before the patient arrives, predict whether the planned service will need prior authorization and whether that PA is likely to be approved. Features available: planned procedure, diagnosis, payer, patient coverage, provider. Intervention: obtain PA proactively, gather supporting documentation, consider alternative covered pathways.

**Pre-billing (coding and submission risk).** After the service is rendered but before the claim is submitted, predict whether the coded claim will be denied. Features available: everything from pre-visit plus actual codes assigned, modifiers, place of service, units. Intervention: fix coding errors, add missing modifiers, attach required documentation, correct diagnosis-procedure mismatches.

**Post-submission (payer behavior prediction).** After the claim is submitted, predict the payer's determination based on the full claim plus payer-specific behavioral patterns. Features available: the complete claim plus payer response history. Intervention: prioritize follow-up, prepare appeal documentation in advance, allocate denial management resources.

Each prediction point is essentially a different model (different features available, different outcome windows, different interventions). Most organizations start with pre-billing because it has the highest ROI: you have the most features available and the intervention (fixing the claim before submission) is the cheapest.

## General Architecture Pattern

```text
[Claims Data Lake] → [Feature Pipeline] → [Model Training (periodic)]
                                        → [Scoring Service (batch + real-time)]
                                        → [Explanation Service]
                                        → [Worklist / Alert Engine]
                                        → [Feedback Loop (actual outcomes)]
```

The pipeline has these logical stages:

1. **Feature pipeline.** Pulls historical claims with outcomes, computes derived features (payer-procedure denial rates, provider denial rates, diagnosis-procedure compatibility scores), and maintains a feature store that's refreshed as new outcomes arrive.

2. **Model training.** Periodic retraining (weekly or monthly) on claims with known outcomes. Trains multiple models: one per prediction point, potentially one per major payer. Evaluates against holdout data with emphasis on precision at the high-risk threshold (you don't want too many false alarms annoying your coders).

3. **Scoring service.** Batch scoring (nightly for all pending claims) and real-time scoring (at the point of claim creation in the billing system). Outputs a denial probability plus top contributing features.

4. **Explanation service.** For each high-risk prediction, generates human-readable explanations: "This claim is flagged because [reason 1], [reason 2], [reason 3]." Maps SHAP values to business-language descriptions.

5. **Worklist engine.** Routes flagged claims to appropriate queues: coding review, documentation requests, PA initiation. Prioritizes by dollar amount multiplied by denial probability (expected loss).

6. **Feedback loop.** When claims are adjudicated (paid or denied), the outcome feeds back into the training data. This is your ground truth. Track model accuracy over time and trigger retraining when performance degrades (payer rule changes are the most common drift source).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.11-architecture). The Python example is linked from there.

## The Honest Take

Let's talk about what makes this harder than it looks on paper.

**Class imbalance is severe and non-uniform.** Your overall denial rate might be 12%, but it varies wildly by payer (Payer A: 8%, Payer B: 22%), by procedure category (E/M visits: 5%, surgical: 18%, DME: 30%), and by time (Q4 denial rates spike as payers tighten year-end budgets). A single global model struggles with this heterogeneity. You'll likely need payer-specific models or at minimum payer-specific features heavily weighted.

**The bias problem is real and subtle.** Your model learns to predict how payers actually behave, including inappropriate denials. If a payer systematically denies claims for a specific demographic or diagnosis category in ways that violate regulations, your model will learn to predict (and implicitly validate) that pattern. A model that says "this claim has 80% denial probability" could be flagging a legitimate coding issue or flagging a claim that the payer will incorrectly deny. You need humans reviewing the flagged claims, not auto-correcting them. The model should surface risk, not make the decision.

**Payer rules change without notice.** A payer adds a new PA requirement or changes their medical necessity criteria, and suddenly your model's predictions for that procedure are stale. The model will catch up after enough claims are denied under the new rules, but there's a lag period where it's underestimating risk. Monitor for sudden accuracy drops per payer-procedure combination and have a process for manual rule updates when you learn about policy changes through other channels (provider bulletins, contract amendments).

**The "fix it before submission" intervention works too well.** Here's the irony. If your model is good and your coders act on the flags, your denial rate drops. Which means your training data shifts: the claims you submit are cleaner, so the model sees fewer denials for the patterns it's catching. This is a success, but it complicates retraining. You need to track which claims were flagged and corrected (counterfactual data) to avoid the model learning that those patterns are safe because they no longer get denied (they no longer get denied because the model flagged them).

**Precision vs. recall is a real tradeoff with operational consequences.** If you flag too many claims (high recall, low precision), your coders develop "alert fatigue" and start ignoring the system. If you flag too few (high precision, low recall), you miss preventable denials. The right threshold depends on your coding staff capacity and the cost of a false alarm (wasted reviewer time) versus the cost of a missed denial (rework cost). This is a business decision, not a model decision. Expect to tune it for months after launch.

**Regulatory and fairness considerations are not afterthoughts.** If your model's denial predictions correlate with patient demographics in ways that result in differential treatment (e.g., claims for certain patient populations get extra scrutiny), you have a fairness problem even if the model is "just predicting what the payer will do." Monitor model performance across demographic groups. Use bias detection tooling (SHAP subgroup analysis, demographic parity metrics) to detect disparate impact. Ensure that the model's predictions don't result in differential access to care or services.

**Be careful with "route to alternative pathway" recommendations.** The model predicts financial outcomes (will the payer pay?), not clinical appropriateness (is this the right treatment?). If the clinically appropriate procedure has a high predicted denial rate, the right answer is to strengthen the PA submission, not to change the treatment plan. Clinical decisions must remain independent of denial predictions. The model's job is to reduce administrative friction for clinically appropriate care, not to optimize treatment selection for financial outcomes. Make this boundary explicit in your operational policies and training materials.

---

## Related Recipes

- **Recipe 7.1 (Appointment No-Show Prediction):** Same supervised classification architecture pattern (feature store, model training, scoring, action engine) applied to a different operational problem. Shares infrastructure and architectural patterns.
- **Recipe 7.2 (Propensity to Pay Scoring):** Complementary revenue cycle prediction. Propensity-to-pay scores patient payment likelihood after a claim is adjudicated; denial prediction scores whether the claim will be adjudicated favorably in the first place. Together they cover both failure modes in the revenue cycle.
- **Recipe 1.4 (Prior-Auth Document Processing):** The Document Intelligence recipe for extracting and processing PA submissions. If your denial prediction model flags "PA required," Recipe 1.4 covers how to automate the PA document preparation.
- **Recipe 1.5 (Claims Attachment Processing):** When the model flags "documentation needed," Recipe 1.5 covers the document intelligence patterns for automatically extracting and attaching clinical documentation to claims.
- **Recipe 3.3 (Billing Code Anomalies):** Anomaly detection for billing patterns complements denial prediction. Anomaly detection finds outliers (unusual coding patterns); denial prediction scores the risk of specific claims.

---

## Tags

`predictive-analytics` · `risk-scoring` · `revenue-cycle` · `claim-denial` · `prior-authorization` · `binary-classification` · `xgboost` · `shap` · `explainability` · `sagemaker` · `batch-transform` · `real-time-inference` · `class-imbalance` · `fairness` · `hipaa` · `medium-complex`

---

*← [Recipe 7.10: Optimal Intervention Timing Prediction](chapter07.10-optimal-intervention-timing-prediction) · [Chapter 7 Index](chapter07-preface) · [Next: Chapter 8 →](chapter08-preface)*
