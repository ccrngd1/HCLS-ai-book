# Recipe 3.5: Lab Result Outlier Detection ⭐

**Complexity:** Medium · **Phase:** MVP+ · **Estimated Cost:** ~$0.0005 to $0.003 per lab result screened (mostly compute and reference-data joins)

---

## The Problem

It's 6:42 a.m. in a 200-bed community hospital. The overnight chemistry analyzer ran a routine basic metabolic panel on a draw collected at 5:15 a.m. from a 74-year-old man admitted the night before for community-acquired pneumonia. The result hits the LIS (laboratory information system) queue: potassium 7.8 mEq/L.

If that number is real, the patient is minutes away from cardiac arrest. The floor nurse gets paged. The hospitalist gets paged. The rapid response team assembles. An EKG is ordered stat. Calcium gluconate, insulin and D50, and a beta-agonist nebulizer are drawn up from the code cart. And the patient, when the nurse gets to the bedside, is sitting up in bed eating oatmeal, asking when breakfast coffee is coming.

Meanwhile, the tech in the lab is looking at the same specimen. The sample was drawn from a peripheral vein, sat in the tube holder at the nursing station for an hour and a half before the courier made pickup, and arrived at the lab visibly hemolyzed. The hemolysis index on the chemistry analyzer is 4+. The potassium reading of 7.8 is almost certainly pseudohyperkalemia from red cells lysing in the tube and releasing their intracellular potassium. A properly drawn peripheral recollect with immediate transport shows potassium 4.2, which matches the patient's previous values and his clinical picture.

Everyone's Saturday morning just got wrecked by a pre-analytical artifact. The rapid response was not wrong to activate; they did exactly what the protocol said to do. The problem is upstream: the result should never have been released to the chart as a valid value without the hemolysis context reaching the clinician at the same time, or without the LIS flagging it as inconsistent with the patient's recent history and holding it for tech review.

That's lab result outlier detection in a nutshell. Labs generate enormous volumes of numerical data on patients, and most of that data is routine. But the outliers fall into three very different categories, and distinguishing between them is the entire problem:

**Category one: the result is real and clinically critical.** The potassium really is 7.8. The patient really is about to arrest. Missing this is fatal. Delaying it is nearly fatal.

**Category two: the result is real but clinically unexpected.** The patient's white count jumped from 9 to 24 overnight. Something changed. It might be infection, it might be steroids, it might be a leukemoid reaction. The clinician needs to see it, understand it, and act on it. Missing it or burying it costs hours of delayed diagnosis.

**Category three: the result is not real.** The sample was hemolyzed, clotted, drawn from an IV line, contaminated with IV fluid, labeled for the wrong patient, processed on a drifted analyzer, or subjected to some other pre- or post-analytical insult. Releasing it as if it were valid causes false alarms, unnecessary interventions, wasted blood draws, and loss of clinical trust in the lab. Missing that the result is artifactual is a patient safety event in its own right.

A traditional LIS handles the "result is real and clinically critical" case reasonably well through critical value rules: if potassium is above some threshold, auto-flag and auto-notify. Those rules have existed for decades, they work, and they're where every lab starts. But they do nothing for the other two categories, and they generate false alarms constantly when category three masquerades as category one.

What you actually want to build is a layered outlier detection system. Rules for the obviously critical values, because the clinical stakes are too high to risk missing them. Patient-specific delta checks that compare the current result to the patient's own recent history, because a potassium of 5.8 is unremarkable in a dialysis patient and is shocking in a healthy postpartum mother. Population-level statistical checks that flag values that are improbable given the patient's demographic and clinical profile. Clinical implausibility checks that catch impossible combinations (a hemoglobin of 18 in a patient whose baseline has been 9 for six months). And underneath all of it, a pre-analytical context layer that tracks specimen quality indicators (hemolysis, icterus, lipemia, clot detection, quantity not sufficient) and flags results that look dramatic but are likely artifacts.

The goal isn't to replace the critical value rules; those are the legal and clinical backstop. The goal is to route results more intelligently: hold questionable results for tech review before they reach the chart, surface the unexpected-but-real results with enough context for a clinician to act quickly, and suppress the noise that's currently training every clinician to distrust every alert. Lab tech and pathologist attention is scarce; clinician attention is even scarcer. Every outlier that gets automated intelligent triage is one less human that has to look at something that doesn't need them.

Let's get into how.

---

## The Technology

### The Three-Stage Lab Workflow, and Where Outliers Hide

Laboratory testing has three phases, and an outlier detection system that ignores any of them will miss huge classes of errors.

**Pre-analytical.** Everything that happens before the specimen enters the analyzer. Order entry (right test on right patient). Specimen collection (right tube, right site, right technique). Transport (right temperature, within stability window). Receipt and accessioning (right barcode, right priority, right condition). The majority of lab errors, depending on which study you read, originate here. Hemolyzed potassiums, clotted CBCs, diluted-by-IV-fluid chemistries, mislabeled specimens, drift due to delayed transport of temperature-sensitive samples. 

**Analytical.** The instrument measurement itself. Modern analyzers are extremely reliable, but they drift. Quality control runs, performed two or three times per shift, catch most drift. But drift between QC events, reagent lot changes, carryover contamination, and interferences from medications or endogenous substances (lipemia, icterus, paraproteins) all introduce analytical error.

**Post-analytical.** Result release, reporting, and clinical interpretation. The result the analyzer produced is correct, but the lab manually transcribed it incorrectly. Or the result was sent to the wrong patient chart because of an LIS mapping error. Or the reference range applied was for the wrong age or sex.

An outlier detection system has an important division of labor with the QC program that runs inside the lab. QC watches the analyzer for drift; it's a process-control problem, not a patient-data problem. The outlier detection we're building here watches the results after they emerge from QC, and its job is to catch the errors that escape QC (especially pre-analytical) and the clinically-significant-but-real outliers that QC is blind to by design. The two systems complement each other; they don't replace each other.

### What "Outlier" Actually Means

There are at least five structurally different outlier types, and a first-time builder who treats them all the same will produce a system that's bad at all of them.

**Hard critical values.** Potassium above 6.5, glucose below 40, hemoglobin below 6, platelets below 20. Defined values that map to clinical danger regardless of patient context. The LIS already has these. The outlier system should respect them as a hard floor: these always fire, always route to the pager, always generate a critical-value callback under CLIA. What the outlier system can add is context (is this consistent with the patient's recent history or is it likely artifactual?) to help the clinician disposition the alert faster.

**Delta check failures.** A change from the patient's previous result that's larger than expected. Hemoglobin drops from 11.2 to 8.4 in four hours. Creatinine climbs from 1.1 to 2.9 in one day. TSH jumps from 2.1 to 18.9 in three weeks. Deltas are the single most clinically useful outlier class because they catch real change while adapting automatically to patient-specific baselines. They also catch specimen misidentification: if the last hemoglobin was 14 and the current one is 7.2, one possibility is bleeding and the other is that the sample came from a different patient. Delta checks have been part of lab practice for decades, but most LIS implementations use naive deltas with fixed thresholds; there's room for statistical refinement here.

**Population-level improbability.** The result is outside the distribution for patients with this demographic and clinical profile. A serum sodium of 118 in an otherwise healthy 35-year-old is a substantial outlier; the same sodium in a patient on psychiatric drugs known to cause SIADH is much less surprising. The improbability is relative to the reference population. Building useful reference populations is a nontrivial data engineering problem because the cohort has to be narrow enough to be informative and broad enough to be stable.

**Clinical implausibility.** The result contradicts other information about the patient. A hemoglobin A1C of 12% in a patient whose last three A1Cs were 5.4, 5.6, 5.5. An undetectable TSH (below 0.01) alongside a free T4 that's within normal range. A creatinine that implies severe renal failure in a patient whose last eGFR a week ago was 85. These don't fit the other categories; they fit a general "this doesn't look like this patient" pattern that requires multi-result reasoning.

**Specimen artifact signals.** Indicators from the analyzer that the specimen was compromised. Hemolysis index, icterus index, lipemia index (these are reported by most modern chemistry analyzers alongside the result). Clot detection from CBC analyzers. QNS (quantity not sufficient) messages. Short sample flags. Reagent lot expiration warnings. These aren't the result; they're metadata about the result, and they have to be fused into outlier detection because they turn what looks like an improbable result into an explainable one.

A mature system handles all five. A useful v1 usually starts with delta checks plus specimen artifact fusion, because those two together catch most of the spurious critical values and the clinically meaningful changes that traditional critical value rules miss.

### Reference Ranges Are More Interesting Than You Think

Every lab report includes a reference range next to each result. The reference range is usually treated as a fixed property of the test, but in practice it's a clinically and statistically complex object.

**Age and sex variation.** A hemoglobin of 11.0 is low for an adult male, low-normal for an adult female, and normal for a 9-month-old. Alkaline phosphatase in an adult is different from alkaline phosphatase in a growing adolescent by a factor of three. Creatinine reference ranges vary with muscle mass, which correlates with age and sex. Almost every analyte has some form of age or sex banding, and a serious outlier detection system has to use those bands rather than a single adult reference range.

**Pregnancy physiology.** Pregnant patients have shifted reference ranges for almost everything. Hemoglobin drops by design (dilutional). Alkaline phosphatase climbs (placental source). TSH has a trimester-specific range. Creatinine is typically lower than baseline. An outlier detector that applies non-pregnancy ranges to pregnant patients will flood the chart with false positives in the second and third trimesters.

**Population-specific intervals.** Some analytes have meaningfully different distributions across populations. Creatinine-based GFR estimating equations historically used a race coefficient that's now been revised. WBC reference ranges for certain African populations skew lower. The appropriate handling is increasingly to use population-aware ranges, with explicit attention to equity and the medical literature.

**Method-specific ranges.** Two different analyzer platforms may report the same analyte in slightly different units or with slightly different calibration, and the reference range reported is specific to the method. When a patient's labs move between facilities or analyzers (which happens routinely), naive delta checks across methods produce spurious flags. The fix is to harmonize against the method and track method changes in the delta calculation.

**Critical values and action values.** Critical values (the narrow range that triggers mandatory callback) are a subset of abnormal values. Action values (a wider range where the result should be reviewed but not necessarily called back) sit between critical and reference range. Many labs distinguish these tiers; a good outlier detector respects them.

Reference ranges come from a few sources: the instrument manufacturer's insert (the starting point), the lab's own validation studies (customized for the local population), published literature (for specialty tests), and for some tests, nationally published consensus intervals (lipids, A1C, TSH in pregnancy). Storing them as first-class data with versioning is important because ranges change when methods change, and reproducing a past alert requires knowing which range was in force.

### Patient-Specific Baselines

Population reference ranges are a blunt instrument. The finer tool is the patient's own history.

**Rolling mean and stddev.** For analytes with reasonable stability in healthy individuals (hemoglobin, creatinine, TSH, albumin), a patient's own past results within a relevant time window produce a tighter reference than any population range. The right window depends on the analyte (days for acute-care chemistry, weeks to months for chronic-care trending). When enough history exists, a z-score against the patient's own mean is often more clinically meaningful than any population-level flag.

**Delta checks as time-local patient baselines.** The patient's immediately previous result is the shortest-window baseline. A delta check is essentially a one-step-lookback z-score scaled by the analyte's expected physiological variation. "Hemoglobin dropped by 2.5 g/dL from yesterday" captures a patient-specific baseline without needing much history.

**CUSUM and change-point detection for slow trends.** Some analytes drift for clinically meaningful reasons that no single delta check catches. Creatinine climbing 0.1 per day for seven days, no single delta above threshold, total change is clinically significant (acute kidney injury). CUSUM charts and change-point detection surface these gradual shifts.

**Analyte-specific handling for intrinsic variability.** Some analytes have high intra-individual variation (glucose in a non-diabetic can swing substantially day-to-day; lipid panels vary with fasting status). The patient-baseline methods have to be calibrated to the analyte's physiology; applying the same delta thresholds across all tests produces nonsense.

### Statistical Methods That Fit

**Rule-based criticality.** The critical value framework baked into every LIS. Hard thresholds for life-threatening abnormalities. Every outlier system incorporates this, both as a clinical floor and as a regulatory requirement.

**Delta checks.** Compare current result to previous result within a window. Flag if the change exceeds analyte-specific thresholds (absolute and percentage). Robust and explainable. Covered in CLIA and CAP guidance.

**Robust z-scores against patient history.** For patients with sufficient prior results, compute a median and median-absolute-deviation on the patient's own historical values. Flag if the current result's robust z exceeds a threshold. Falls back to population-level when patient history is sparse.

**Population z-scores against demographic cohorts.** Cohort definition uses age band, sex, and clinical attributes (pregnancy, dialysis, known disease states). Same robust-z approach, broader baseline.

**Specimen quality index fusion.** Every reportable result gets the analyzer's specimen quality indices joined. Rules combine result outlier status with quality indices: a critical potassium with a 4+ hemolysis index gets held for tech review rather than released as-is.

**Time-series methods (CUSUM, EWMA) on slow drifts.** For analytes that drift clinically relevant amounts over days to weeks without triggering single-event thresholds, control-chart methods on the patient's series surface the drift.

**Multivariate outlier detection (Isolation Forest, Mahalanobis distance).** A patient's full chemistry panel is a multivariate observation. Flag results that are outliers in the multivariate space even when no single component crosses a threshold (an implausible combination of sodium, potassium, BUN, creatinine, and glucose that no single value catches). Particularly useful for catching specimen artifact patterns and lab error patterns that manifest across multiple results.

**Cross-test coherence checks.** Encode known physiological relationships between results and flag inconsistencies. TSH very low plus free T4 normal (unusual, suggests non-thyroidal illness or artifact). Sodium and glucose inconsistency. Hemoglobin and hematocrit out of the expected 3:1 ratio. Bilirubin fractions that don't sum consistently. These are rule-based but operate across multiple results within the same panel.

**Supervised classifiers when labels exist.** If the lab captures pathologist review outcomes, autoverification overrides, or confirmed artifact events, train a supervised classifier on the feature vector (result value, delta, specimen indices, patient context) to predict artifactual vs. real. Labels are usually biased toward the cases someone looked at; treat the classifier as a triage signal on flagged events rather than a primary detector.

**LLM-assisted interpretation (emerging).** A HIPAA-eligible LLM can read the result alongside the patient's recent clinical notes and active diagnoses to flag results that don't fit the clinical picture. Still experimental, expensive to run per result, useful as a triage layer on already-flagged results rather than a primary screen.

A reasonable technical progression: start with rule-based critical values and analyte-specific delta checks, add specimen quality fusion, add patient-history robust z-scores, add cross-test coherence checks, add multivariate Isolation Forest on panels, add supervised re-ranking once review labels exist. Don't skip the first two layers; they catch most of the real clinical signal and anchor the system's explainability.

### The Autoverification Connection

Most modern LIS installations have an autoverification feature: a rules engine that decides which results are released to the chart automatically versus held for technologist review. Autoverification rates above 90% are common for routine chemistry and hematology in efficient labs; the goal is that technologist attention is spent on the small fraction of results that actually need a human look.

The autoverification rules engine and the outlier detection pipeline are the same architectural idea wearing different hats. Autoverification is "is this result safe to release without human review?" and outlier detection is "does this result look unusual enough that someone should pay attention to it?" They share the input data (the result, specimen indices, patient history, reference ranges), they share the model machinery (rules plus statistical checks plus multivariate patterns), and they produce complementary outputs (release vs. hold; alert vs. quiet). Serious deployments unify them rather than running them as separate pipelines.

The practical consequence: the outlier detector can be the brain of the autoverification decision. A result that fires no outlier flag autoverifies. A result that fires a "specimen artifact suspected" flag holds for tech review. A result that fires a "clinically critical" flag autoverifies AND fires a critical-value callback. The routing is just the outlier output plus the existing callback rules.

### Alert Fatigue, Again

This recipe shares a problem with Recipe 3.4 (Medication Dispensing Anomalies) and every other clinical alerting domain: over-alerting destroys clinical trust. The consequence in the lab context is that every lab critical value call that arrives when the clinician doesn't think the result is plausible (pseudohyperkalemia from hemolysis, false hypoglycemia from a diluted sample) erodes the clinician's confidence in the next critical value call.

The design implications:

- Clinical critical values must still fire under CLIA. No suppression. But the alert payload should include specimen quality context and recent-history context so the clinician can disposition faster.
- Delta-check thresholds need per-analyte calibration to the lab's population. Default thresholds from the LIS vendor are a starting point, not an endpoint.
- Patient-context-aware suppression for low-value alerts is explicitly allowed. A "slightly abnormal" result in a patient whose history shows this is their baseline doesn't need a prominent flag.
- Override tracking is not optional. Every time a clinician disregards or the lab tech overrides an alert, capture the reason. That's the training signal for calibration.

Lab alerting has a specific flavor of alert fatigue that the medication side doesn't: the lab tech has a different cost/benefit calculation than the clinician. For the tech, false positives mean extra recollections and extra work. For the clinician, false positives erode trust and waste attention. The two have to be optimized together, not independently.

---

## General Architecture Pattern

At a conceptual level, a lab outlier detection pipeline has to do two things at once: serve real-time screening for results arriving from the analyzers (low-latency, per-result decisions that gate autoverification and callback), and run longer-window pattern detection for cohort-level and trend-level signals. Under both sits a shared reference data layer (reference ranges, analyte metadata, rule library) and a shared patient-context layer (demographics, recent results, active problems, medications).

```
┌──────────────── LAB OUTLIER DETECTION PIPELINE ───────────────────┐
│                                                                   │
│   [Analyzers] → [Middleware] ─┐                                   │
│   [POCT devices] ─────────────┤                                   │
│   [Reference lab feeds] ──────┤                                   │
│                               ▼                                   │
│              [LIS / Result Router]                                │
│                               │                                   │
│                               ▼                                   │
│                [Result Normalizer + LOINC Mapper]                 │
│                (unit harmonization, method tracking,              │
│                 specimen-quality index capture)                   │
│                               │                                   │
│                               ▼                                   │
│                [Patient-Context Cache]                            │
│                (demographics, pregnancy, active dx,               │
│                 meds, recent results, baselines)                  │
│                               │                                   │
│           ┌───────────────────┼────────────────────────┐          │
│           ▼                   ▼                        ▼          │
│  REAL-TIME SCREEN     PATIENT-BASELINE PATH    CROSS-TEST PATH    │
│                                                                   │
│   [Critical-Value    [Rolling Mean/Stddev]      [Coherence        │
│    Rule Engine]       [Delta Checks]             Rule Engine]     │
│   [Reference-Range   [Robust Z-scores]          [Panel-level      │
│    Check]             [CUSUM / Drift]            Isolation        │
│   [Specimen-Quality                              Forest]          │
│    Fusion]                                                        │
│           │                   │                        │          │
│           ▼                   ▼                        ▼          │
│                [Flag Aggregator + Severity Tiering]               │
│                               │                                   │
│                               ▼                                   │
│                [Routing]                                          │
│                  │  │  │                                          │
│                  │  │  └───► Autoverify (release to chart)        │
│                  │  └──────► Tech Review Queue (hold)             │
│                  └─────────► Critical-Value Callback + Alert      │
│                              (page clinician, log callback)       │
│                                                                   │
│                [Feedback Capture]                                 │
│                  (tech override reasons, recollect outcomes,      │
│                   clinician response, confirmed artifact events)  │
│                               │                                   │
│                               ▼                                   │
│                [Retraining / Threshold Tuning]                    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

**Ingest.** Results arrive from heterogeneous sources. The main analyzers in the central lab push results to the LIS through a middleware layer (Data Innovations Instrument Manager, Beckman Remisol, Sysmex Caresphere, others). Point-of-care testing devices stream through a POCT data manager (RALS, Telcor, Conworx). Send-out results from reference labs arrive via HL7 v2 ORU messages or a proprietary file feed. Each source carries different specimen-quality metadata in different formats; the normalizer has to capture all of it.

**Result normalization.** Every result gets mapped to a LOINC code if not already present, units harmonized to the canonical form for that analyte (mg/dL vs. mmol/L for glucose, for example), method recorded, and reference range attached based on the patient's age, sex, pregnancy status, and the method. Specimen-quality indices (hemolysis, icterus, lipemia, clot, QNS flags) travel with the result as first-class fields. This layer is where lab-specific content rules live: "for this analyzer method, lipemic index above X invalidates triglyceride"; "for this POCT glucose, values above Y must be reflex-tested on the central analyzer."

**Patient-context cache.** Demographics, pregnancy status, active problem list, active medication list, recent results (last 30 days for most analytes, longer for chronic markers), baseline statistics (rolling mean and stddev per analyte for this patient), current encounter attributes (acuity, location, reason for admission). Populated from EHR and LIS feeds with defined freshness windows per field.

**Real-time screen.** For each result as it arrives, run the rule engine (critical value rules, reference range check, specimen-quality gating rules) and produce a result-level decision. Latency budget: tens of milliseconds. Output is structured flags that drive the routing.

**Patient-baseline path.** Delta checks against the most recent prior result. Rolling-mean robust z-scores against the patient's historical distribution. CUSUM on the patient's time series for drift detection. Runs per-result but can be slightly async (hundreds of milliseconds acceptable) because these don't gate the autoverification-critical latency. Method-harmonization is a first-class concern in the delta-check layer: when the current result and the prior result were produced by different analyzer methods (a routine occurrence in dual-platform labs, satellite labs, and analyzer-downtime re-routing), a naive absolute-delta comparison produces false flags. The delta computation must compare the `method` field between current and previous results, apply a documented harmonization coefficient where one exists, and suppress the absolute-delta check (emitting a metric for monitoring) where no harmonization data is available. The patient-history robust z-score remains valid across methods because it uses the patient's full historical distribution.

**Cross-test path.** Runs on complete panels, not individual results. When all components of a chemistry panel are available, run the coherence rules (anion gap plausibility, Na-glucose consistency, bilirubin fractions summing) and the panel-level Isolation Forest scorer. Batched per panel, typically sub-second per panel.

**Flag aggregator and severity tiering.** Combines flags from all three paths into a per-result (or per-panel) decision. Severity tiering determines routing: critical-clinical (autoverify and callback), release-with-flag (release but surface to chart), tech-review-hold (hold for tech review before release), retest-required (hold and request recollection). The thresholds are clinical and operational decisions governed by the lab director and clinical leadership.

**Routing.** Release to the chart, hold for tech review, or trigger a critical-value callback. Callback is a CLIA-regulated workflow: the callback has to happen within a defined window, be documented, and be closed out with read-back. The routing infrastructure must support this documented workflow, not just fire-and-forget alerts.

**Feedback capture.** Tech review decisions (released as-is, recollected, method-suppressed, manual-verify) get logged. Clinician response to critical value callbacks (acknowledged, modified orders, ordered recollect, ordered treatment) gets logged. Confirmed pre-analytical artifact events (the recollection came back with a different value, confirming the initial result was an artifact) get linked to the original flag. This feedback is the training signal for rule tuning and supervised model training.

**Retraining and threshold tuning.** Monthly or quarterly cadence. Review override rates by rule and by analyte; retire or re-threshold rules with high override rates. Retrain supervised models on accumulated labels. Review confirmed-artifact events for patterns missed by current rules. Update reference ranges when validation studies identify population drift.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.05-architecture). The Python example is linked from there.

## The Honest Take

Delta checks do more work than any other single component, and most teams underestimate them. I've watched multiple projects chase sophisticated ML approaches for lab anomaly detection while their delta-check thresholds were still at the vendor defaults from an implementation done seven years ago. Tuning the delta thresholds analyte by analyte based on the lab's actual population and clinical workflow is unglamorous work that pays off more than any model improvement. The patients you care about, at the moment you care about them, almost always have a prior result in the chart. Use it. If you're only doing one thing, do delta checks well.

Specimen quality fusion is the single biggest lever nobody talks about. Modern chemistry and hematology analyzers emit specimen quality indices alongside the result, and most LIS implementations treat those indices as informational rather than decisional. Joining the indices with the result in the alerting logic catches the vast majority of pre-analytical artifacts (pseudohyperkalemia from hemolysis is the textbook case, but the same pattern applies to icterus inflating LDH, lipemia interfering with almost everything, IV contamination crashing electrolytes). Teams that skip this layer build detectors that are great at catching real clinical outliers and terrible at distinguishing them from lab artifacts. That combination is what trains clinicians to distrust the lab.

The critical-value callback workflow is more complex than it looks. New teams tend to think of "fire an alert" as a simple action. In a regulated lab, the callback is a timed, documented, read-back-verified workflow with escalation rules when the primary target can't be reached. Getting the automation for this right is 40% of the engineering effort in the critical-path part of the pipeline, and it's the part that will be inspected during accreditation surveys. Build it carefully and document the timing. Assume your audit logs will be read.

Reference ranges encode more complexity than you expect. The first time I asked "what's the reference range for this test?" I assumed there was one range in a table. There are seven, differentiated by age, sex, pregnancy, method, and two lab-specific customizations. A version of this table has changed three times in the last five years. The ranges that were in force when a particular alert fired may no longer be the ranges in force today. Treat reference ranges as versioned first-class data, not as a config file. Audit trails that don't record which range was in force for a given alert are not audit trails; they're wishes.

The autoverification story is where the ROI lives. Most labs have autoverification rates in the 60-85% range for routine chemistry, lower for specialty tests. Raising that rate from (say) 72% to 88% in a mid-size lab eliminates thousands of tech reviews per week. The savings are real. But the wrong way to go after the improvement is "relax the hold rules until more results pass through." The right way is to improve the signal: better delta check calibration, better specimen quality fusion, better patient-context awareness, better cohort modeling. When the signal gets sharper, you can hold the hold-rate down (reviewing fewer false positives) while maintaining the same safety net. That's where the outlier detector becomes a business case, not just a safety feature.

The patient-specific baseline is more useful than the population cohort baseline in most cases. Population cohort baselines are noisy. Patients vary so much in their individual set points (hemoglobin normal distribution for "adult female" is enormous; for a specific adult female with two years of history, much narrower) that patient-specific baselines outperform cohort baselines for patients with enough history. The caveat is that many of your encounters are with patients who don't have enough history in your system: ED patients, new admissions, outpatient visitors. For those, the cohort baseline is still the best you have. Build both; route each result to the better-fitting one.

The thing that surprised me: the cross-test coherence rules caught things I didn't expect. Anion gap plausibility, TSH/T4 consistency, bilirubin fractions summing, sodium-glucose consistency. These are rule-based checks, not ML, and they caught a disproportionate fraction of lab error patterns: analyzer calibration drift, reagent dispense errors, specimen mislabeling where the wrong patient's results ended up on the wrong panel. I initially built them as a nice-to-have. They ended up being one of the most reliable layers in the pipeline. Don't skip the coherence rules because they feel low-tech.

The thing I'd do differently: I spent too long building the multivariate Isolation Forest before understanding how to present its output. "This panel's anomaly score is -0.71" is not a reviewable finding. The tech needs to know: which components are unusual together, compared to what baseline, and what does that pattern typically indicate. Generating the SHAP-based explanation alongside the score, with a curated set of "this combination often means X" narrative templates, was a second project after the model was built. Do the explainability work first. Model without explanation is a generator of mysterious alerts that techs override blindly.

The trap to avoid: do not let "flag rate" become the primary business metric. The flag rate (flags per 1000 results) is a symptom metric; it can be driven up or down by tuning thresholds without any change in clinical value. The metrics that matter are autoverification rate (higher is better, subject to not compromising safety), pre-analytical artifact catch rate (higher is better, measured against recollect confirmations), real critical-value miss rate (lower is better, measured against chart-reviewed ground truth or downstream clinical signals), and callback timeliness (CLIA-compliant, higher compliance is better). Frame the program around these. Flag rate is a knob to adjust, not a goal.

The politics: the lab and the clinical teams view alerts differently. A lab director thinks of flag rate as a workload indicator. A clinical team thinks of flag rate as a signal-to-noise indicator. A good outlier detection deployment serves both constituencies, which means the severity tiering and routing design has to be co-owned. Don't build it with only lab leadership or only clinical leadership in the room. Both perspectives shape the final operating point.

---

## Related Recipes

- **Recipe 3.1 (Duplicate Claim Detection):** Shares the real-time-screening-plus-batch-aggregation pattern. The ingest and event routing architectures are closely related.
- **Recipe 3.2 (Patient No-Show Pattern Detection):** Shares the patient-level-baseline plus population-cohort-baseline hybrid. Different domain, structurally identical statistical framing.
- **Recipe 3.3 (Billing Code Anomalies):** Shares the rules-plus-statistical-plus-multivariate layered detection pattern.
- **Recipe 3.4 (Medication Dispensing Anomalies):** The closest neighbor. Medication anomaly and lab outlier pipelines share most of their infrastructure patterns (patient-context cache, severity tiering, feedback capture, CLIA-adjacent governance). In mature deployments, medication and lab anomaly pipelines often share AWS services.
- **Recipe 3.7 (Patient Deterioration Early Warning):** The trajectory detection layer of this recipe produces signals that feed into deterioration scoring. Lab trend features (rising lactate, rising creatinine, dropping bicarbonate) are core inputs to sepsis and deterioration risk models.
- **Recipe 3.9 (EHR Access Pattern Anomalies):** Shares the feedback-driven retraining loop and the per-user-baseline approach for a subset of detection targets.
- **Recipe 8.x (Clinical Text Normalization):** Extraction of active problems and medications from free-text notes (for the patient-context cache) is covered in Chapter 8. Critical input to reference-range selection and patient-context features.
- **Recipe 12.x (Clinical Time Series):** Patient trajectory analytics (CUSUM, change point detection) for lab trends overlap heavily with Chapter 12's time-series techniques. The implementations often share code.
- **Recipe 13.x (Clinical Knowledge Graphs):** Cross-test coherence rules benefit from a physiological knowledge graph that encodes expected relationships between analytes. Chapter 13 covers construction of clinical knowledge graphs.

---

## Tags

`anomaly-detection` · `laboratory` · `clinical-decision-support` · `autoverification` · `critical-value-callback` · `delta-check` · `specimen-quality` · `hemolysis` · `reference-range` · `patient-baseline` · `cohort-baseline` · `statistical-process-control` · `cusum` · `isolation-forest` · `kinesis` · `lambda` · `dynamodb` · `sagemaker` · `feature-store` · `opensearch` · `comprehend-medical` · `bedrock` · `hl7` · `fhir` · `loinc` · `clia` · `medium` · `mvp-plus` · `hipaa` · `provider`

---

*← [Recipe 3.4: Medication Dispensing Anomalies](chapter03.04-medication-dispensing-anomalies) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.6 - Healthcare Fraud/Waste/Abuse Detection →](chapter03.06-healthcare-fraud-waste-abuse-detection)*
