# Recipe 7.1: Appointment No-Show Prediction

**Effort:** 1 of 5

---

## The Problem

Here's a number that should make any clinic operations manager wince: somewhere between 5% and 30% of scheduled outpatient appointments end up as no-shows. The patient just doesn't come. No call, no cancellation, no reschedule. The slot sits empty.

That empty slot isn't free. A primary care physician's time is worth roughly $200-400 per hour, depending on specialty and market. A 15-minute slot that goes unused is $50-100 of lost revenue. Multiply that across a 20-provider practice with a 15% no-show rate, and you're looking at hundreds of thousands of dollars in annual lost revenue. For a large health system with hundreds of providers, the number crosses into the millions.

But the financial hit is only part of the story. That empty slot could have gone to another patient. Someone who needed to be seen. Someone on a waitlist. Someone whose condition is getting worse while they wait three weeks for the next available appointment. No-shows don't just cost money; they cost access.

The standard response has been blunt-force overbooking: schedule 110% of capacity and hope the math works out. Sometimes it does. Sometimes three patients all show up for two slots and the waiting room turns hostile. Overbooking without intelligence is a gamble, and the downside is a terrible patient experience for the people who did show up on time.

What if you could predict which specific appointments are likely to no-show? Not "15% of Tuesday afternoon appointments" as a population average, but "this specific appointment with this specific patient has a 73% chance of being missed." That changes everything. You can send targeted reminders to high-risk appointments. You can selectively overbook only the slots most likely to open up. You can offer waitlisted patients those specific slots as standby options. You can allocate staff time toward outreach rather than hoping for the best.

This is one of the cleanest prediction problems in healthcare operations. Binary outcome (showed vs. didn't show). Abundant historical data (every scheduling system has years of it). Low-stakes intervention (a reminder call or text). And the feedback loop is immediate: you find out within hours whether your prediction was right.

Let's build it.

---

## The Technology: Predicting Human Behavior from Patterns

### Binary Classification: The Foundation

At its core, no-show prediction is a binary classification problem. Given a set of features about an upcoming appointment, predict one of two outcomes: the patient will show up, or they won't. This is the bread and butter of machine learning, and it's been well-understood for decades.

The simplest version is logistic regression: a mathematical function that takes a weighted combination of input features and squishes the result into a probability between 0 and 1. If the output is 0.73, you interpret that as "73% chance of no-show." It's interpretable, fast, and surprisingly effective for this problem. Many production no-show models in healthcare are still logistic regression under the hood, because the features matter more than the algorithm.

Gradient-boosted trees (XGBoost, LightGBM, CatBoost) are the next step up. They build an ensemble of decision trees, each one correcting the errors of the previous ones. They handle non-linear relationships, feature interactions, and missing values more gracefully than logistic regression. For tabular data like appointment records, they're typically the best-performing approach without requiring deep learning infrastructure.

Deep learning (neural networks) is overkill for this problem in most cases. The data is tabular, the feature space is modest, and the relationship between features and outcome isn't complex enough to justify the training overhead. Save neural networks for problems where you have unstructured data (images, text, sequences) or millions of training examples with subtle patterns.

### The Features That Actually Matter

Here's what decades of no-show research have consistently found to be predictive:

**Patient history.** The single strongest predictor of a future no-show is past no-shows. A patient who missed 4 of their last 10 appointments has a dramatically higher probability of missing the next one than a patient with a perfect attendance record. This is the "prior behavior predicts future behavior" principle, and it dominates most models.

**Lead time.** The gap between when the appointment was scheduled and when it's supposed to happen. An appointment booked 6 weeks out has a much higher no-show rate than one booked 2 days out. This makes intuitive sense: life changes, people forget, the urgency that prompted the booking fades.

**Day and time.** Monday mornings and Friday afternoons tend to have higher no-show rates. So do appointments during school hours for pediatric patients. These patterns are highly local to your specific practice and patient population.

**Appointment type.** Follow-up visits no-show at higher rates than new patient visits. Routine wellness checks no-show more than urgent symptom visits. The perceived urgency of the visit matters.

**Demographics and access factors.** Distance from the clinic, transportation access, insurance type (Medicaid populations historically show higher no-show rates, reflecting access barriers rather than irresponsibility), age, and language barriers all correlate with no-show probability. These features improve accuracy but require careful handling to avoid reinforcing disparities (more on this in the Honest Take section).

**Weather and external events.** Rain, snow, extreme heat, and local events (school closures, major sports events) all measurably affect no-show rates. These are harder to incorporate because they require external data sources and real-time feature computation, but they can add a few percentage points of accuracy.

**Reminder history.** Whether the patient has already received a reminder, and whether they confirmed. A patient who confirmed via text 24 hours ago is much less likely to no-show than one who hasn't responded to any outreach.

### Why This Is Easier Than Most Healthcare ML

No-show prediction has several properties that make it unusually tractable:

**Clear, objective outcome.** The patient either showed up or didn't. There's no ambiguity, no subjective labeling, no inter-rater disagreement. Your training labels are clean.

**Abundant data.** Any scheduling system with 2+ years of history has tens of thousands of labeled examples. You don't need to go find data or label it manually. It's already there.

**Fast feedback loop.** You know the outcome within hours of the prediction. This means you can retrain frequently, detect model drift quickly, and measure your accuracy in near-real-time.

**Low-stakes intervention.** If your model says "high risk of no-show" and you send an extra reminder, the worst case is a mildly annoyed patient who was going to show up anyway. Compare that to a model that recommends a medication or a surgical intervention. The cost of a false positive here is a text message.

**No regulatory burden.** This isn't a clinical decision support tool. It's an operational optimization. You don't need FDA clearance, you don't need clinical validation studies, and you don't need physician sign-off on the model's recommendations. (You do still need to handle protected health information (PHI) appropriately, but that's table stakes in healthcare.)

### The General Architecture Pattern

The pipeline has four logical stages:

```text
[Feature Store] → [Model Training] → [Scoring Service] → [Action Engine]
```

**Feature Store.** A pre-computed repository of patient and appointment features, updated on a schedule. Raw data from your scheduling system, EHR, and demographics tables gets transformed into model-ready features: no-show rate over the last N appointments, days since last visit, distance to clinic, appointment lead time, and so on. Computing these on the fly at prediction time is possible but slow and fragile. A feature store decouples feature engineering from model serving.

**Model Training.** A batch process that trains (or retrains) the classification model on historical appointment data. Runs on a schedule (weekly or monthly) or when triggered by performance degradation. Outputs a serialized model artifact and a performance report: area under the curve (AUC), calibration curve, feature importance.

**Scoring Service.** An inference endpoint that accepts an appointment's features and returns a no-show probability. This runs in near-real-time: when a new appointment is booked, or on a nightly batch for the next day's schedule. The output is a probability (0.0 to 1.0) and optionally the top contributing features (for explainability).

**Action Engine.** The system that decides what to do with the prediction. Above a certain threshold, trigger an extra reminder. Above a higher threshold, flag the slot for overbooking consideration. Below the threshold, do nothing special. The thresholds are operational decisions, not model decisions. They depend on your reminder capacity, your overbooking tolerance, and your patient experience goals.

This separation of concerns is important. The model predicts. The action engine decides. Changing your reminder strategy shouldn't require retraining the model, and improving the model shouldn't require changing your operational workflows.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.01-architecture). The Python example is linked from there.

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Uses patient preferences and response history to choose the best reminder channel (SMS, email, phone, app notification) for the interventions triggered by this recipe's predictions.
- **Recipe 7.4 (ED Visit Prediction):** Similar binary classification approach but predicting emergency department utilization rather than appointment attendance. Shares feature engineering patterns.
- **Recipe 7.5 (30-Day Readmission Risk):** Another predictive model with a well-defined binary outcome and established benchmarks. Demonstrates the same train/score/act pipeline at higher clinical stakes.
- **Recipe 12.1 (Appointment Volume Forecasting):** Complements no-show prediction by forecasting aggregate demand. Together, they enable intelligent capacity planning.

---

**Tags:** `predictive-analytics`, `binary-classification`, `no-show`, `scheduling`, `operations`

---

---

## Tags

`classification` · `predictive-analytics` · `calibration` · `patient-engagement` · `scheduling` · `hipaa` · `dynamodb` · `eventbridge` · `glue` · `lambda` · `sagemaker`
