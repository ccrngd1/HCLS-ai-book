# Recipe 12.8: Disease Progression Trajectory Modeling ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$800–$3,500 per month per disease-cohort workload

---

## The Problem

A 54-year-old woman with autosomal dominant polycystic kidney disease has been followed at the same nephrology clinic for nine years. Her chart contains 41 separate eGFR results, 38 measurements of total kidney volume from MRI, a dozen blood pressure logs that drift up and to the right, and a careful record of her ACE inhibitor titrations. Every individual data point is unremarkable in isolation. Each clinic visit ends with a reasonable-sounding plan that mostly amounts to "let's recheck in six months." But if you stand back and look at the full nine-year trajectory, what jumps out is that her kidney function is on a near-linear decline of about 4.2 mL/min/1.73 m² per year, and total kidney volume is growing at roughly 6% annually. At that rate, plus or minus the uncertainty inherent in nine years of irregular measurements, she is likely to need renal replacement therapy somewhere between her sixty-second and sixty-seventh birthday. That is a different conversation than "let's recheck in six months." It is a conversation about transplant evaluation timing, vascular access planning, and whether to enroll in a tolvaptan trial that might bend the curve.

That conversation is not happening, and the reason is not that her care team is bad. The cognitive work it requires (integrating nine years of irregular measurements across multiple variables, accounting for treatment effects, factoring in disease-specific progression rates, communicating future-state uncertainty in a way that is actionable on a multi-year horizon) is not what a 20-minute outpatient nephrology visit is structured to do. Each visit is a snapshot. The trajectory lives across snapshots and across an analytic gap that the EHR was never designed to bridge.

This pattern repeats across most chronic, slowly progressive diseases. A patient with non-alcoholic fatty liver disease has serial fibroscan elastography readings creeping upward over four years; the trajectory predicts cirrhosis in a clinically actionable timeframe long before any single value crosses a transplant-eligibility threshold. A patient with Parkinson's disease has a UPDRS motor score that has been climbing two points per year for five years, with a six-month plateau coinciding with a medication change; the trajectory says something about how their next decade looks, and the slope changes around the medication say something about which therapy will and will not extend their function. A patient with multiple myeloma has serum free light chains that drift up over eighteen months in a near-imperceptible curve until the day they cross a numerical threshold; the trajectory was visible in retrospect for a year before the threshold was crossed.

The promise of disease progression trajectory modeling is exactly this: take the longitudinal record of a patient with a known chronic, progressive disease, fit a model that captures the disease-specific shape of progression along with patient-specific deviations from that shape, account for the effects of interventions that bend or reset the trajectory, and produce a forward-looking forecast that is calibrated, explainable, and clinically actionable on a multi-year time horizon. Done well, you give the patient and their care team a horizon to plan against. Done poorly, you produce confident-looking projections that come apart on first contact with reality, the patient stops trusting the system the first time it is wrong, and the clinician learns to ignore it.

This is not the same problem as the lab trend analysis covered in Recipe 12.4. Lab trend analysis asks "has the recent trajectory deviated from the patient's recent baseline in a way that warrants attention?" Trajectory modeling asks "what does this patient's disease look like over the next two, five, ten years, and how do interventions change that?" The first is a change-detection problem on a horizon of months; the second is a forecasting-and-counterfactual problem on a horizon of years. The math overlaps. The clinical use case, the regulatory framing, and the failure modes are different.

Let's get into how this works.

---

## The Technology: How Disease Progression Trajectory Modeling Actually Works

### The Three Things You Are Actually Modeling

Trajectory modeling for a chronic disease is, at its core, three nested things stacked on top of each other. Most people who have not built one of these tend to underestimate how much the layered structure matters.

**The disease-specific progression shape.** Each chronic disease has a characteristic curve. Kidney function in chronic kidney disease tends to decline approximately linearly in eGFR over years, with a slope that varies dramatically by etiology and patient phenotype. Total kidney volume in autosomal dominant polycystic kidney disease grows roughly exponentially, with the doubling time being itself a clinically meaningful biomarker. Functional status in idiopathic pulmonary fibrosis follows a curve that is shallower at first and steepens. Cognitive decline in Alzheimer's disease has a roughly sigmoidal trajectory on standard scales, with a long preclinical plateau and an accelerating mid-disease phase. Tumor growth, on the other hand, is typically modeled as a Gompertzian curve where the growth rate slows as the tumor approaches its carrying capacity. The shape comes from biology, not from the data, and using the wrong shape is the single most common cause of unhelpful trajectory models. A linear fit to a Gompertzian process produces predictions that are wrong in clinically meaningful ways at both early and late time points.

**The patient-specific deviation from that shape.** Every patient with a given disease deviates from the population-average shape by some amount. They may have a faster or slower disease, a different starting point, a delayed onset of certain features, or unusual responses to treatment. The patient-specific layer captures this. Statistically, this is what mixed-effects models and Bayesian hierarchical models are designed for: the disease shape is the population fixed effect, the patient deviation is the per-patient random effect. Done correctly, the per-patient model borrows strength from the population (so that a patient with three measurements is not modeled in isolation) but respects the individual signal (so that a clearly fast-progressing patient is not pulled toward the population mean).

**The intervention effects that bend the trajectory.** Treatments are the third layer and they are the layer that makes this problem genuinely hard. Starting tolvaptan in autosomal dominant polycystic kidney disease changes the kidney volume trajectory in a way that depends on the patient's baseline volume, the dose, and the duration. Starting an SGLT2 inhibitor in CKD changes the eGFR trajectory in a way that includes an immediate, expected, downward step (the so-called "dip") followed by a slower long-term decline. Surgical resection of a tumor resets the trajectory entirely, with new growth modeled from the post-operative residual. Chemotherapy and targeted therapy produce response patterns that interact with tumor biology in ways that vary across cancer types. The intervention layer requires the model to know about treatments as time-varying covariates, and it requires the clinical question being asked of the model to be specific about what intervention scenario the projection assumes. "What is this patient's eGFR in five years?" is not a complete question. "What is this patient's eGFR in five years if they continue on lisinopril at current dose, with no new interventions?" is a question the model can actually answer.

### Statistical Approaches in Production

The methods that show up in working systems cluster into a few families. None of them is universally best, and most working systems use more than one.

*Linear mixed-effects models* fit a fixed effect for disease shape (often after a transformation that linearizes the underlying biology) and random effects per patient. They are interpretable, they handle irregular sampling natively, and they produce calibrated uncertainty intervals if you respect their assumptions. For diseases with approximately linear progression on the right scale (CKD on eGFR, slow-progressing dementia on standardized cognitive scales), linear mixed-effects models are very hard to beat. The R [`lme4`](https://github.com/lme4/lme4) and Python [`statsmodels`](https://www.statsmodels.org/stable/mixed_linear.html) implementations are standard. The clinical research literature for a given disease usually establishes the right transformation; do not invent your own.

*Non-linear mixed-effects models* generalize the previous family to non-linear functional forms. The disease shape might be a Gompertz curve, a logistic curve, a Richards curve, or some other parametric form motivated by the biology. The patient-specific parameters (asymptote, growth rate, inflection point) are modeled as random effects. These work well when the biology has a known parametric shape. They are less interpretable than linear mixed effects and need more data per patient to fit reliably, but they extrapolate more sensibly to long horizons.

*Bayesian hierarchical models* extend the previous families with full posterior uncertainty. The advantage is that prior knowledge from disease-specific literature can be incorporated explicitly: the population-level slope of eGFR decline in a CKD cohort is not unknown, it has been studied for decades, and that prior should anchor the model. The model produces a posterior distribution over patient-specific parameters, which means forecasts come with calibrated credible intervals out of the box. PyMC, Stan, and NumPyro are the workhorses; the trade is computational cost and engineering complexity for explicit uncertainty quantification.

*Joint models for longitudinal and time-to-event outcomes* are the right answer when the question is not just "what is the trajectory" but "given the trajectory, when does the patient hit a clinically meaningful endpoint?" In CKD, this might be "when does eGFR drop below 15, the threshold for renal replacement therapy?" Joint models simultaneously fit the longitudinal trajectory and the time-to-event hazard, with the trajectory acting as a time-varying predictor of the hazard. The [JM](https://cran.r-project.org/web/packages/JM/) and [JMbayes2](https://github.com/drizopoulos/JMbayes2) R packages and the Python [lifelines](https://lifelines.readthedocs.io/) library cover this space. For high-stakes clinical questions about endpoint timing, joint models are the architecturally right answer.

*Gaussian processes and continuous-time state-space models* handle irregular sampling natively and are useful when the disease does not have a clean parametric form. They produce smooth trajectory estimates and forecasts with built-in uncertainty intervals. They are more flexible than parametric models but less interpretable, and they extrapolate poorly beyond the support of the training data. They are well-suited to functional status and quality-of-life outcomes that have noisy, drifting trajectories without a clean biological shape.

*Deep learning approaches* (recurrent neural networks, neural ordinary differential equations, transformer-based survival models) have shown promise in research settings, particularly for diseases with complex multi-modal data (imaging plus labs plus genetic markers). They can learn the population-level disease shape from data without the modeler specifying a parametric form, and they integrate naturally with embedding-based representations of treatment history. They cost a lot more than the alternatives in data, compute, explainability, and regulatory exposure. In 2026, most production deployments still favor the simpler families above for the routine cases and reserve deep learning for diseases where the competing methods have visibly failed.

### Sparse, Irregular, and Multi-Year

The features that make this problem particularly hard are inherent to the data, not to any specific algorithm. A typical patient with CKD has eGFR measured every three to six months in a stable phase, every six weeks during a regimen change, and not at all during the eighteen months they spent uninsured between jobs. The same patient might have one MRI taken five years ago when the diagnosis was made and never again. Their blood pressure log is dense for two years and then disappears for three. Their medication history is, at best, a structured list of prescriptions written; whether they actually took the pills is a separate question that nobody is sure about.

This is the data the model has to consume, and the methods that handle it best share a few characteristics: they work natively in continuous time rather than requiring a regular grid, they are robust to right-censoring (some patients drop out of follow-up for reasons that are both random and informative), they tolerate or impute missing covariates without making heroic assumptions, and they do not extrapolate confidently beyond the time horizon supported by the training data. Methods that quietly violate any of these assumptions produce forecasts that look fine in cross-validation and fall apart in production. The cross-validation failure mode that catches teams off guard is leakage of future information into past predictions through poorly handled missing data; if a patient's six-month-future eGFR was used to impute their three-month-future blood pressure, the model is going to look a lot smarter on retrospective data than it actually is.

### The Acute-Versus-Chronic Distinction (Revisited)

As in lab trend analysis, the chronic and acute contexts are fundamentally different problems. A trajectory model trained on outpatient eGFR measurements will produce confidently wrong forecasts if the input data includes inpatient values from a hospitalization with acute kidney injury. The standard practice is to tag every input measurement with its clinical context and use only chronic-context measurements for the trajectory model. Acute-context measurements feed Recipe 12.7 (Vital Sign Trajectory Monitoring) or other acute-care pipelines. Mixing the two produces a trajectory model that is whipsawed by acute episodes, which clinicians correctly recognize as not telling them anything they did not already know.

### Counterfactual Thinking and the "What If" Question

The clinically interesting question is rarely "what is this patient's trajectory under no change," because by the time the patient is on the model's radar there is usually some change being considered. The interesting question is "how does the trajectory change if we start tolvaptan, switch from lisinopril to losartan, add an SGLT2 inhibitor, refer for transplant evaluation now versus in six months." This is a counterfactual question, and a model that only forecasts the observed-treatment trajectory cannot answer it.

The principled approaches here come from causal inference: g-computation, marginal structural models with inverse probability weighting, and target trial emulation are standard in the epidemiology literature. They require explicit modeling of the treatment-assignment mechanism and they require strong assumptions about unmeasured confounders. For diseases with strong randomized clinical trial evidence on intervention effects (CKD, ADPKD, several oncology contexts), the simpler approach is to use the published trial-derived effect sizes as plug-in priors: the trajectory model captures the natural history, and the published effect of tolvaptan on kidney volume growth gets applied as an explicit modifier with appropriate uncertainty propagation. This is less elegant than a fully causal model but it is much more defensible regulatorily and produces forecasts that clinicians can sanity-check against the trial literature they already know.

The point to internalize: any "what if" capability in a trajectory system is doing causal inference whether it admits it or not. The choice is between explicit, defensible assumptions and implicit, unexamined ones.

### Where the Field Is Actually Going

The practical state of the art in 2026 looks roughly like this. For diseases with strong clinical research foundations and well-characterized progression curves (CKD, ADPKD, several neurodegenerative diseases, several oncology indications), production trajectory systems combine a Bayesian hierarchical model with disease-specific priors, an explicit treatment-effect layer driven by the published trial literature, a joint model for the time-to-clinical-endpoint outcome, and a careful interface that emphasizes the uncertainty bands as much as the central forecasts. For diseases with weaker research foundations or more complex multi-modal data (rare diseases, certain pediatric conditions, mixed phenotype presentations), the systems lean more on flexible Gaussian process or deep learning models, with the explicit caveat that long-horizon extrapolation is unreliable and the model is positioned as a "trajectory characterizer" rather than a "future-state predictor."

The clinical adoption arc looks like this: the model has to be accurate enough to be trusted, explainable enough to be acted on, and uncertainty-honest enough to be defended in front of a patient. Models that fail any of those three tests get unplugged. Models that pass all three tend to get adopted and then re-adopted as the cohort grows and as new evidence shifts the priors.

### The General Architecture Pattern

At a conceptual level, the pipeline looks like this:

```text
[Longitudinal Patient Data] -> [Cohort Definition + Harmonization] -> [Trajectory Model Training]
                                                                              |
                                                                              v
                                                          [Per-Patient Trajectory Inference]
                                                                              |
                                                          +-------------------+-------------------+
                                                          |                   |                   |
                                                          v                   v                   v
                                                 [Counterfactual          [Time-to-          [Uncertainty
                                                  Treatment Scenarios]    Endpoint]            Bands]
                                                          |                   |                   |
                                                          +-------------------+-------------------+
                                                                              |
                                                                              v
                                                                [Clinical Interface Layer]
                                                                              |
                                                                              v
                                                  [Clinician + Patient + Care Team]
```

**Longitudinal Patient Data.** EHR-sourced labs, vitals, imaging-derived measurements, medication history, problem lists, and outcomes. Often pulled from multiple systems and reconciled.

**Cohort Definition and Harmonization.** Patients are placed in a disease cohort by phenotype (ICD codes, lab thresholds, problem-list entries, sometimes confirmatory imaging or genetic testing). Within the cohort, longitudinal measurements are harmonized to canonical units, canonical codes, and canonical reference frames (time-since-diagnosis, time-since-treatment-start, calendar time as appropriate to the disease). Acute-context measurements are excluded from the chronic trajectory.

**Trajectory Model Training.** A disease-specific model is fit on the cohort. The model captures the population-level disease shape, the patient-specific deviations, and the effects of interventions present in the training data. Disease-specific priors from the clinical literature are incorporated where appropriate.

**Per-Patient Trajectory Inference.** For each patient in the cohort, the model produces a fitted trajectory through their observed history and a forward forecast under the assumption of "no new interventions" (or, equivalently, "current treatment continued").

**Counterfactual Treatment Scenarios.** Optionally, the model produces additional forecasts under alternative treatment scenarios specified by the clinician (start tolvaptan, switch antihypertensive class, add SGLT2 inhibitor, refer for transplant). Each scenario produces its own trajectory and uncertainty band. The trial-literature-derived effect sizes drive the modifier in the simpler architecture; explicit causal models drive it in the more advanced one.

**Time-to-Endpoint.** A joint model or analogous time-to-event component produces a probability distribution over when the patient hits a clinically meaningful endpoint (renal replacement therapy in CKD, dementia diagnosis in cognitive trajectory work, structural progression milestone in cardiology). This is often the most clinically actionable single output of the pipeline.

**Uncertainty Bands.** Every forecast comes with credible intervals. The intervals are not optional; they are the reason the trajectory matters. A point forecast of "your eGFR will be 28 in five years" is much less useful than "we are 90% confident your eGFR will be between 22 and 35 in five years, with current treatment continued."

**Clinical Interface Layer.** The forecasts get rendered for the clinical user. The interface decisions matter as much as the modeling decisions. Trajectory plots with uncertainty bands, time-to-endpoint hazard curves, and side-by-side counterfactual comparisons are the standard surfaces. The interface explicitly communicates what assumptions the forecast embeds, especially the treatment-continuation assumption.

**Clinician, Patient, Care Team.** The forecasts inform a multi-stakeholder conversation: the patient and their family planning around a multi-year horizon, the care team coordinating around testing and referral cadence, the specialist deciding when to escalate. The model is one input to that conversation, not the conversation itself.

That is the whole concept. Cohort, model, infer, counterfactual, communicate. The hard parts are concentrated in the cohort/harmonization layer, the treatment-effect modeling, and the clinical interface, not in the trajectory math itself. (You will notice this is becoming a theme in this chapter. It is not a coincidence.)

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter12.08-architecture). The Python example is linked from there.

## The Honest Take

The math, again, is the easy part. (You will notice this is the third time I have made this observation in this chapter, which is itself a kind of confession.) The first time I built a disease progression trajectory model, I spent eight weeks on the model itself, two weeks on the data plumbing, and assumed I was eighty percent done. I was twenty percent done. Six months later I had spent another twelve weeks on cohort governance, harmonization quality, calibration monitoring, treatment-effect prior maintenance, and the clinical interface, and I was still finding new ways the system could be subtly wrong.

The thing that surprised me was how much of the work is actually about disagreement management. The clinical team has a strong intuitive prior on how kidney function behaves in their patients. The model has its own prior, conditioned on a different cohort, with different treatment patterns, in different decades, with different measurement methods. When the model and the clinician disagree, who wins? Sometimes the model is right and the clinician's intuition was anchored on an outdated cohort. Sometimes the clinician is right and the model is hallucinating signal from a peculiarity of the training data. The system needs an interface that surfaces the disagreement productively rather than presenting either side as authoritative. That is harder than it sounds.

Calibration is the easiest thing to get wrong and the easiest to fix once you notice. The first version of the first system I built had 90% credible intervals that empirically contained 73% of held-out observations, and the calibration backtest revealed it within two weeks. The fix was a hierarchical recalibration on the per-patient random effects; conceptually simple, but the system would have been quietly producing overconfident forecasts for at least a year if we had not built calibration monitoring from day one. The lesson: the calibration backtest is not optional, and it is not something to add later. Build it on day one or you will regret it.

The thing I underestimated, repeatedly, is the cohort definition. A "patient with chronic kidney disease" sounds like a well-defined clinical concept. It is not. There is the clinical guideline definition (eGFR < 60 sustained over three months), the registry definition (the patient has been seen in nephrology), the billing definition (an N18 ICD-10 code has been entered), and the actual-care-team definition (the PCP has internalized that this patient has CKD), and these four overlap incompletely. The trajectory pipeline has to pick one definition and stick with it, and changing the definition retroactively reshapes every downstream forecast. Engineers underestimate this because the definitions look interchangeable in the data. They are not. Clinicians underestimate this because they assume the engineering side has it under control. It does not, by default. Make the cohort definition a first-class versioned artifact owned by both sides.

The other thing I underestimated, less repeatedly because at this point the lesson has been learned, is the regulatory framing. A trajectory system that says "this patient's eGFR will probably be 28 in five years" is, in the FDA's eyes, much closer to a diagnostic claim than the team building it intuitively believes. The 21st Century Cures Act CDS exemption is generous but not unlimited; the transparency and explainability requirements have to be built into the system as architectural primitives, not added as a documentation pass at the end. The "explanation_text" and "assumption_disclosure" fields in the example payload exist because the regulatory framing forced them to exist. Build the system that way from the start and the regulatory conversation is a discussion. Build it the other way and the regulatory conversation is a redesign.

The part that worked better than I expected is the counterfactual layer driven by trial-literature priors. Coming from a more academic background, I initially wanted to build a fully causal model with explicit confounder adjustment, target trial emulation, and the full machinery. The plug-in approach (use the published trial effect sizes as priors and propagate uncertainty) felt like a compromise. In practice it produced forecasts that clinicians could sanity-check against the trials they already trusted, satisfied the regulatory framing more easily, and was an order of magnitude cheaper to build and maintain. The fully causal approach is the right answer for deeper research questions; the plug-in approach is the right answer for the production trajectory system.

Finally: the explanation matters even more than in lab trend analysis, because the time horizon is longer and the clinical implications are heavier. A forecast that says "your patient's eGFR will be 28 in five years" is too thin. A forecast that says "based on your patient's nine-year history, comparable patients in our cohort, and current treatment continued, we project a 90% probability that eGFR is between 22 and 35 in five years; starting tolvaptan now would shift that range upward by approximately 4 mL/min/1.73 m^2 based on the published trial evidence" is something the patient and the care team can actually plan around. The narrative is the product, not the math. Again.

---

## Related Recipes

- **Recipe 12.4 (Lab Result Trend Analysis):** The shorter-horizon, single-lab counterpart that handles the chronic-trend signal. Trajectory modeling builds on the harmonization and baseline layers used there but extends to multi-year, multi-variable forecasting with counterfactual scenarios.
- **Recipe 12.7 (Vital Sign Trajectory Monitoring):** The acute-context counterpart focused on real-time inpatient deterioration. Different cadence, different clinical workflow, but shares the state-space and credible-interval machinery.
- **Recipe 12.9 (Epidemic Forecasting):** Population-level forecasting with comparable uncertainty-management challenges; trajectory modeling is per-patient, epidemic forecasting is per-population, but the calibration and communication patterns are similar.
- **Recipe 6.x (Cohort Analysis and Clustering):** Cohort definition is the foundation of trajectory modeling. The phenotype-clustering recipes in Chapter 6 inform the cohort identification strategies used here.
- **Recipe 7.x (Predictive Analytics and Risk Scoring):** Risk scoring is essentially a one-step-ahead version of trajectory modeling. The two recipes share architectural primitives; the trajectory recipe extends to long horizons and counterfactual reasoning.
- **Recipe 4.10 (Dynamic Treatment Regime Recommendation):** The reinforcement-learning approach to treatment-decision-making at multiple time points; conceptually adjacent to the counterfactual layer in trajectory modeling.
- **Recipe 13.x (Knowledge Graphs and Ontology):** Disease cohort definitions, drug classifications, and clinical phenotype hierarchies live in the broader clinical-terminology ecosystem covered there.

---

## Tags

`time-series` · `disease-progression` · `trajectory-modeling` · `mixed-effects` · `bayesian-hierarchical` · `joint-models` · `survival-analysis` · `counterfactual` · `causal-inference` · `chronic-disease` · `ckd` · `adpkd` · `oncology` · `neurodegenerative` · `cohort-definition` · `calibration-monitoring` · `clinical-decision-support` · `cds-hooks` · `healthlake` · `sagemaker` · `dynamodb` · `step-functions` · `complex` · `production` · `hipaa` · `samd`

---

*← [Previous: Recipe 12.7 - Vital Sign Trajectory Monitoring](chapter12.07-vital-sign-trajectory-monitoring) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.9 - Epidemic Forecasting →](chapter12.09-epidemic-forecasting)*
