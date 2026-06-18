# Recipe 12.9: Epidemic Forecasting ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$1,200-$5,000 per month per regional surveillance workload

---

## The Problem

It is the second week of October, and a state epidemiologist is staring at three dashboards on three monitors trying to decide whether something is happening. The first dashboard shows respiratory virus PCR positivity from the state public health lab, climbing from 4.1% to 6.8% over the last fourteen days. The second shows emergency department chief-complaint counts for "fever," "cough," and "shortness of breath" from the syndromic surveillance feed, drifting upward across most of the state's reporting hospitals but not in a way that would individually cross any single alert threshold. The third shows wastewater SARS-CoV-2 RNA concentrations from twelve sentinel sites, with two sites in the same county already two-and-a-half standard deviations above their summer baseline. None of these signals alone is screaming. Together they are saying, quietly but consistently, that something is starting.

The question on the epidemiologist's desk is not "is there an outbreak right now." That question gets answered by the outbreak detection pipeline (Recipe 3.10), and the answer is currently "early signal, not yet confirmed." The question is "what does the next four to twelve weeks look like." Specifically: do we activate the regional surge plan, do we issue early guidance to long-term care facilities, do we ask the governor's office to authorize emergency PPE procurement, and do we tell hospitals to start delaying non-urgent elective procedures. Each of those decisions has a multi-million-dollar cost if taken unnecessarily, and each has a several-multi-million-dollar cost if not taken when it should have been. The decision the epidemiologist actually has to make is to estimate, with calibrated uncertainty, the trajectory of cases, hospitalizations, and ICU admissions over the next several weeks, conditional on what is currently observed and on plausible policy and behavior responses.

That is the epidemic forecasting problem. It is not the same as outbreak detection. Outbreak detection asks "is this signal anomalous given baseline." Epidemic forecasting asks "given that something is starting, where does it go." The first is essentially a change-detection problem on a horizon of days to weeks. The second is essentially a transmission-dynamics-and-uncertainty-quantification problem on a horizon of weeks to months. The math overlaps. The data sources overlap. The clinical and policy stakeholders overlap. The decision-making stakes are dramatically different, and the failure modes are dramatically different.

The COVID-19 pandemic made this concrete for everyone who lived through it. In March 2020 the question wasn't whether something was happening. It was how bad it would get, how fast, and where, and whether your hospital had two weeks or six weeks before ICU capacity was breached. The forecasts that informed those decisions came from a patchwork of academic groups, federal agencies, and ad-hoc state coalitions, and the lessons learned were brutal. Forecasts that ignored behavior change were confidently wrong. Forecasts that didn't communicate uncertainty got blamed when reality landed in the lower or upper tail. Forecasts that updated too slowly were ignored. Forecasts that updated too quickly looked unstable and got ignored a different way. Forecasts that were communicated as point estimates ("cases will peak at X on date Y") were treated as guarantees and produced political fallout when reality diverged. Forecasts that were communicated honestly as probabilistic ranges were sometimes ignored because the ranges felt too wide to be useful.

The same dynamics apply, with smaller stakes but the same structure, to seasonal influenza, RSV, norovirus, measles outbreaks in under-vaccinated communities, mpox in close-contact networks, vector-borne diseases in changing climate zones, and emerging pathogens that have not yet had their global moment. Public health forecasting groups have been doing this work for decades. The platform engineering side of it, the part that turns the forecast into a production system that updates daily, ingests heterogeneous data feeds, communicates uncertainty to non-statistical stakeholders, and operates under the regulatory and political pressures that come with public health, is a large and largely under-discussed body of work.

The promise of a production epidemic forecasting system: take the multi-source surveillance data your jurisdiction is already collecting, fit transmission-dynamic and statistical forecasting models that capture the underlying epidemiology along with calibrated uncertainty, refresh forecasts on a cadence that matches public health decision cycles, surface them in formats that policymakers and operators can act on, and update them transparently as new data lands. Done well, you give the public health team a defensible decision-support system that improves response speed and reduces both over-reaction and under-reaction errors. Done poorly, you produce forecasts that get cited in press conferences, fail in ways that erode public trust, and ultimately get ignored.

Let's get into how this works.

---

## The Technology: How Epidemic Forecasting Actually Works

### The Two Families of Models

Epidemic forecasting in production tends to be dominated by two families of models, with a third family increasingly showing up at the margins. Most working systems run an ensemble that combines approaches from each.

**Compartmental (mechanistic) models.** These are the SIR, SEIR, SEIRS, and friends, the family of models that describes the population as a small number of compartments (Susceptible, Exposed, Infectious, Recovered, sometimes more) and writes down differential equations for how individuals flow between them. The rate of new infections depends on how often susceptible people contact infectious people and how likely each contact is to transmit. The basic reproduction number R0 (or its time-varying version Rt) drops out of the model parameters. Compartmental models force you to think mechanistically about transmission, which is both their strength and their cost. Strength: when a vaccination campaign rolls out or a behavior change happens, you can encode it into the model in a principled way. Cost: real epidemics happen in heterogeneous populations across space, age, contact networks, and behavior, and a faithful compartmental model has to multiply compartments to capture that heterogeneity, which gets expensive fast. Production compartmental models often look like SEIR with age-stratification, geographic stratification, vaccination status, prior immunity status, and time-varying contact patterns. The classic [`SEIR`](https://en.wikipedia.org/wiki/Compartmental_models_in_epidemiology#The_SEIR_model) family extends to dozens of variants depending on the disease.

**Statistical and machine-learning models.** These are the time-series forecasters: ARIMA, exponential smoothing, generalized additive models, gradient-boosted trees on lagged features, recurrent neural networks, and the various foundation-model time-series approaches that have shown up since 2023. They learn the patterns from the data without forcing a mechanistic structure. Strength: they are flexible, fast to fit, and they pick up patterns the compartmental model misses if its structure is mis-specified. Cost: they are uninformed about transmission dynamics, which means they extrapolate confidently into regimes that violate epidemiology. A pure ARIMA fit to early-pandemic case counts will happily project exponential growth indefinitely; an SEIR model that captures the susceptible depletion will not. Statistical models are at their best for short-horizon forecasts in stable regimes (most of seasonal influenza, most weeks of most respiratory virus seasons) and at their worst when behavior changes or when the population susceptibility shifts (early outbreaks, post-vaccination periods, novel variant emergence).

**Agent-based and network models.** These simulate individual people (or households, or contact units) and their interactions. They are computationally expensive and rarely the right answer for routine forecasting, but they are valuable for scenario analysis and for situations where heterogeneity is the point (school closure scenarios, workplace policy modeling, contact-tracing-aware projections). They show up in the production stack as a specialized capability invoked for specific policy questions, not as the workhorse forecaster.

The empirical lesson from the [CDC's FluSight](https://www.cdc.gov/flu-forecasting/about/index.html) and [COVID-19 Forecast Hub](https://covid19forecasthub.org/) collaborative forecasting projects is that ensemble forecasts (combining predictions from a dozen or more independently developed models) consistently outperform any individual model. The ensemble is the production answer. The individual model in your jurisdiction is an input to the ensemble, not the final word.

### Multi-Source Data Fusion (Why This Is Different From Other Forecasting)

What makes epidemic forecasting genuinely distinct from other time-series forecasting is the sheer heterogeneity of input signals. A forecasting system that uses one signal is missing the point. The signals you fuse, in a typical respiratory-virus production system:

*Lab confirmed cases* from public health laboratories and reporting clinical labs. This is the gold-standard signal but it lags by days to weeks, depending on test turnaround and reporting delay. Reported case counts also depend on testing capacity and behavior, which themselves are time-varying.

*Emergency department syndromic surveillance.* Visits with relevant chief complaints (fever, cough, shortness of breath, rash, gastrointestinal symptoms depending on the pathogen) tracked through systems like [BioSense](https://www.cdc.gov/nssp/biosense/index.html) or local equivalents. Less specific than lab confirmation but earlier; an ED-syndromic signal can move days to weeks before lab confirmations catch up.

*Hospitalizations and ICU admissions.* Higher specificity than ED visits, lower specificity than lab confirmation. They lag the case curve but they are the operationally critical metric for surge capacity planning.

*Mortality.* Lags by another two to four weeks behind hospitalizations. Useful for retrospective calibration but rarely informative for forward-looking forecasts.

*Wastewater surveillance.* Pathogen RNA or DNA concentrations in sewage. The wastewater signal often leads the clinical signal by four to ten days, depending on the pathogen. It is also less subject to testing-behavior bias than reported cases. The [CDC National Wastewater Surveillance System](https://www.cdc.gov/nwss/wastewater-surveillance.html) standardized much of this for the US after COVID-19. Wastewater signals are noisier than lab counts and require careful quality control, but for early-trajectory estimation they are increasingly the most useful single signal.

*Vaccination coverage by geography and age.* Time-varying input to the susceptibility compartment in mechanistic models. Available from immunization information systems with varying lag depending on the jurisdiction.

*Mobility data.* Aggregated, anonymized movement data from cell phones (when ethically obtainable and with appropriate data-use agreements) provides a near-real-time proxy for contact rates. Used heavily during COVID-19. The signal is informative but the privacy and ethical concerns are real.

*Behavioral surveys.* Self-reported masking, distancing, and contact behavior from rolling surveys (like CDC's [COVID-19 Trends and Impact Survey](https://covidcast.cmu.edu/) collaboration with Carnegie Mellon and Facebook). Lower temporal resolution but higher specificity for capturing intentional behavior change.

*Climate and weather.* For seasonal respiratory viruses, temperature and humidity drive transmission rates. For vector-borne diseases, temperature and rainfall drive the vector population dynamics.

*Population demographics and contact matrices.* Not time-varying on the forecast scale but essential as model structure. The age-stratified contact matrix from sources like the [POLYMOD study](https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.0050074) or its post-pandemic updates is the standard input.

*School and workplace calendars.* Predictable behavior change. School holidays and reopening dates produce reliable, anticipated shifts in contact rates.

The art of fusion is in nowcasting (estimating the current epidemiological state given that all of these signals lag and noise differently) and in propagating the nowcast uncertainty into the forward forecast. A forecast that nowcasts the current state with overconfidence will be miscalibrated forward, regardless of how well the forecasting machinery itself is built.

### Behavioral Feedback and the Counterfactual Trap

This is the part of epidemic forecasting that catches almost everyone off guard the first time they build one of these systems.

Epidemics are not weather. The weather forecast for next week does not change based on the forecast itself. If the forecast says "rain Thursday," people might reschedule their picnic, but the weather does what the weather does. Epidemics are not like that. If the forecast says "ICU surge in three weeks," public health officials issue guidance, hospitals defer elective surgery, the public increases masking, and behavior shifts in ways that materially change the trajectory. The forecast is an input to the system being forecast.

This creates a peculiar epistemological situation. When the forecast is "right" (cases peak where projected), it's often because behavior responded to the forecast in the way the forecast assumed. When the forecast is "wrong" (cases peak lower than projected), it's often because behavior responded more strongly than assumed, which is in some sense the forecast doing its job. The COVID-19 era produced a steady stream of public commentary saying "the model was wrong, cases peaked lower than predicted," which was sometimes true in a narrow technical sense and sometimes a misreading of how forecasts under behavioral feedback work.

The standard production response is scenario forecasting. Rather than producing a single "what will happen" forecast, the system produces multiple "what would happen if" forecasts: under continued current behavior, under modeled mitigation A (mandatory masking), under modeled mitigation B (school closures), under modeled mitigation C (vaccination campaign acceleration). Each scenario has its own trajectory and uncertainty band. The decision-maker's job, with public health input, is to choose which scenarios are policy-relevant and to interpret the comparison.

This is not a complete escape from the counterfactual problem. Each scenario embeds assumptions about behavior change that may or may not actually obtain. But it is a more honest framing than a single point forecast, and it shifts the conversation from "the model says X will happen" to "the model says these are the consequences of these choices." That is the right conversation.

### Calibrated Uncertainty (And Why It Is Hard)

Calibrated uncertainty is the technical foundation of any forecasting system that has to inform high-stakes decisions. A 90% prediction interval that empirically contains 90% of out-of-sample observations is calibrated. A 90% interval that empirically contains 60% is overconfident. A 90% interval that empirically contains 99% is underconfident. Both miscalibration directions cause problems: overconfidence leads to under-preparation, underconfidence leads to dismissal of the forecast as too vague.

Epidemic forecasting calibration is hard for reasons that compound:

*The data-generating process is non-stationary.* Each year's flu season has different dominant strains, different vaccine effectiveness, different behavior context. A forecasting model calibrated on the last five flu seasons may be miscalibrated for the next one in ways that only become visible after the fact.

*The training data is sparse for novel events.* The whole reason novel-pathogen forecasting is hard is that there is no historical data on the specific novel pathogen. Calibration on similar past events is the best you have, and "similar" is doing a lot of work.

*Behavioral feedback corrupts retrospective evaluation.* If you look back at a forecast made in week T for week T+4 and check whether week T+4 fell in the prediction interval, you are evaluating the forecast under the actual behavior path that obtained, which may have been influenced by the forecast itself. Cleanly separating forecast error from feedback effects requires care.

*Multi-resolution targets multiply.* Public health forecasts have to be calibrated at multiple horizons (1, 2, 4, 8 weeks ahead), at multiple geographies (state, region, country), and for multiple targets (cases, hospitalizations, deaths). Calibration may be acceptable at one resolution and broken at another.

The standard tools (probabilistic scoring rules like the [Continuous Ranked Probability Score](https://en.wikipedia.org/wiki/Scoring_rule#Continuous_ranked_probability_score), interval coverage by horizon, the [Weighted Interval Score](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008618) used by the COVID-19 Forecast Hub) come from the broader probabilistic forecasting literature. The discipline is to compute them continuously, surface them on the operational dashboard, and treat calibration drift as a first-class incident type.

### Where the Field Is in 2026

Five years after COVID-19 forced a forced upgrade of public health forecasting infrastructure, the production state of the art looks roughly like this:

For *seasonal respiratory viruses* (flu, RSV, recurring SARS-CoV-2 strains), production systems run weekly ensembles combining mechanistic compartmental models with statistical learners, with wastewater and syndromic surveillance as primary nowcast inputs, lab confirmation as the calibration anchor, and probabilistic forecasts at the state and regional level on horizons out to four to eight weeks. The CDC FluSight and the multi-pathogen [Outbreak Analytics Network](https://www.cdc.gov/forecast-outbreak-analytics/index.html) work serve as the federal coordination layer.

For *novel pathogens or unusual outbreaks* (a mpox emergence, an avian flu spillover concern), the same pipelines extend into a more research-mode posture: compartmental models with prior-based parameter estimation, more frequent recalibration, scenario forecasting weighted toward the policy questions of the moment, and tighter coupling to the outbreak investigation team.

For *vector-borne and zoonotic diseases* (West Nile, Lyme, dengue in expanding climate zones), the forecasting incorporates climate and ecology models for vector population dynamics, longer time horizons, and spatial structure modeled at finer resolution (county or sub-county) because the heterogeneity is sharp.

The institutional pattern is increasingly federation: state and local public health departments run their own forecasting workflows that ingest national-level inputs, contribute to national-level ensembles, and serve their own decision-makers with locally tuned views. The technology stack to support this kind of federated, heterogeneous, probabilistic, multi-source forecasting is genuinely heavy, and the public health workforce has only recently caught up to operating it as production infrastructure rather than research code.

### The General Architecture Pattern

Conceptually, the pipeline looks like this:

```text
[Multi-Source Surveillance Feeds] -> [Data Harmonization + Nowcasting]
                                              |
                                              v
                                  [Per-Model Forecast Generation]
                                              |
                          +-------------------+-------------------+
                          |                   |                   |
                          v                   v                   v
                  [Compartmental         [Statistical/ML       [Scenario
                   Models]                Models]              Models]
                          |                   |                   |
                          +-------------------+-------------------+
                                              |
                                              v
                                    [Ensemble Combination]
                                              |
                                              v
                                  [Calibration + Validation]
                                              |
                                              v
                          [Probabilistic Forecasts + Scenarios]
                                              |
                                              v
                       [Public Health Decision Surfaces]
                                              |
                                              v
                  [Epidemiologists, Policymakers, Hospital Operations,
                   Public Communication]
```

**Multi-Source Surveillance Feeds.** Lab data, syndromic data, hospitalizations, wastewater, vaccinations, mobility, behavioral surveys, climate. Each with its own latency, format, geography, and quality characteristics.

**Data Harmonization and Nowcasting.** Bring all signals to common geographies, common time grids, and common units. Estimate the current epidemiological state, with uncertainty, given that all signals lag and noise. Nowcasting is its own modeling problem, often with its own dedicated models, and its output (with uncertainty) is the input to the forecasting layer.

**Per-Model Forecast Generation.** Run each model family on the harmonized inputs. Compartmental models produce trajectories under specified parameter posteriors. Statistical models produce direct trajectory forecasts. Scenario models produce conditional trajectories under specified policy or behavior assumptions.

**Ensemble Combination.** Combine the per-model forecasts using calibration-aware weighting (often inverse-variance, sometimes by past Weighted Interval Score, sometimes equal-weighted as a simple-but-robust default). The ensemble produces the headline forecast and the uncertainty quantification.

**Calibration and Validation.** Continuously evaluate forecast performance against observed outcomes. Track calibration metrics by horizon, geography, and target. Detect drift. Recalibrate or retrain as warranted.

**Probabilistic Forecasts and Scenarios.** The output artifact: probability distributions over future cases, hospitalizations, ICU admissions, deaths, by geography, by horizon. Scenarios are first-class outputs, not afterthoughts.

**Public Health Decision Surfaces.** The interfaces that make forecasts actionable: dashboards for epidemiologists, briefing-ready visualizations for policymakers, machine-readable feeds for hospital systems, public-facing summaries with uncertainty rendered in lay-accessible formats.

**Stakeholder Layer.** State and local epidemiologists, public health leadership, hospital operations teams (Recipe 12.5 for census forecasting integration), school and workplace decision-makers, emergency management, and the public via communications staff.

The hard parts are concentrated in the harmonization and nowcasting layer, the calibration and validation infrastructure, and the decision-surface layer. The forecasting math is genuinely hard but it is also the most documented and tooled part of the stack. The data engineering and the communication interface are where most production systems quietly fail.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter12.09-architecture). The Python example is linked from there.

## The Honest Take

The math is genuinely beautiful, and almost beside the point. Compartmental models, state-space nowcasting, ensemble combination weighting, scoring rules, calibration evaluation: these are mature pieces of statistics and applied math, and the people who built them are some of the most thoughtful applied statisticians in the field. None of that mathematical elegance saves you from the data engineering. The first time I worked on a production epidemic forecasting system, I spent six weeks getting the harmonization right, two weeks getting the nowcasting working, and one week on the actual forecasting math. The ratio is not an exception, it is the norm.

The thing that keeps surprising me is how much of the work happens at boundaries. The boundary between the lab data feed and the harmonized analytic store. The boundary between the nowcast output and the forecast input. The boundary between the per-model forecasts and the ensemble. The boundary between the ensemble forecast and the operational dashboard. The boundary between the analyst who interprets the forecast and the policymaker who acts on it. Each boundary is a place where an assumption can quietly change. The lab feed switched its case-counting definition at the start of the year. The nowcast started reporting in different units. The ensemble dropped a model that was misbehaving. The dashboard rounded the quantiles. The analyst summarized "the model says cases will increase" without conveying the uncertainty band. Each of these is small in isolation. Stacked together they produce forecasts that are subtly wrong in ways nobody can isolate.

The COVID-19 era taught the entire field a lesson about behavior. Forecasts that ignored behavioral feedback were confidently wrong. Forecasts that tried to model behavior endogenously were either tractable but wrong or correct but uncomputable. The compromise that production systems landed on, scenario forecasting with explicit assumption disclosure, is honestly compromised: it is the right answer in the absence of a better answer, and it is also a way of admitting that the central forecasting question ("what will happen") cannot be answered without the answer to a counterfactual question that we cannot answer with confidence ("what will people do"). The discipline is to state the assumption clearly, run the relevant scenarios, and let the policymaker choose which scenario to act on. The discipline is not satisfying.

Calibration, again, is the easiest thing to get wrong and the easiest thing to fix once you measure it. Every forecasting system I have worked on or evaluated has discovered, on first careful evaluation, that its prediction intervals were either too narrow (overconfident) or too wide (underconfident). Sometimes both, at different horizons. The fix is usually some version of recalibration or ensemble weighting adjustment, and it works. The lesson is that calibration evaluation is not optional and is not something to add after launch. It is the operational metric that determines whether the forecast can be trusted, and it has to be measured continuously and surfaced to the team running the system.

The thing I underestimated, repeatedly, is the political and communication context. A forecast is a number. An interval is a number plus uncertainty. A scenario is a conditional projection. None of these are how policymakers and the public read forecasts. They read forecasts as predictions, and they read predictions as commitments, and they hold the forecaster to the commitment when reality diverges. The defense against this misreading is exhaustive transparency: every forecast surfaces with its assumption disclosure, its uncertainty band, its scenario set, and its calibration history. Doing this is unglamorous and feels redundant. Not doing it is how forecasting groups end up testifying to legislatures about why their projections did or did not pan out.

The part that worked better than I expected is the multi-source fusion. Coming from a more clinical-data background, I initially thought wastewater would be a noisy adjunct to the lab data. In practice, for many respiratory pathogens, the wastewater signal leads the clinical signal by a meaningful number of days, and that lead time is exactly what makes the forecast useful for hospital surge planning. The first few weeks I watched a state's wastewater signal climb out of baseline two weeks before the lab signal followed it, I changed my mind about which signal was the primary input and which was the secondary. For many production use cases, wastewater is the primary nowcast input and the clinical signals are the validation.

Federation is the answer for almost every jurisdiction. Almost no state has the analytical capacity to build, maintain, and validate a forecasting system in isolation. The federal forecast hubs, the academic forecasting groups (CMU's [Delphi group](https://delphi.cmu.edu/), the various university statistics-for-pandemics centers, and the laboratories that contribute to the federal hubs), and the commercial forecasting providers all contribute to the same ensemble, and the ensemble is what you should consume even if your group is one of the contributors. The instinct to build everything in-house is, in this domain, expensive and counterproductive. Build your jurisdiction's contribution to the federation, consume the federation's ensemble, and tune the displayed forecasts to your local decision-making context.

Finally: the forecast is the conversation, not the artifact. A forecast that is right and not communicated produces no value. A forecast that is communicated badly produces negative value (the dashboard that confused a county commissioner during the pandemic and led them to delay a mitigation by two weeks, which I have heard about from more than one health department, was technically correct and operationally catastrophic). The narrative around the forecast, the way it is rendered, the language used to describe it, the placement of the uncertainty bands, the framing of the scenarios: these are the product. The math is the foundation. The product is the conversation. Build for the conversation.

---

## Related Recipes

- **Recipe 3.10 (Epidemic / Outbreak Detection):** The detection counterpart to the forecasting recipe here. Detection asks "is something starting"; forecasting asks "where does it go." Production public health systems run both and integrate them through shared surveillance ingestion.
- **Recipe 12.3 (ED Arrival Forecasting):** Hospital-level demand forecasting that consumes regional epidemic forecasts as an input feature for surge planning.
- **Recipe 12.5 (Hospital Census Forecasting):** Inpatient census forecasting that integrates with regional epidemic forecasts to anticipate surge-driven admissions and ICU capacity needs.
- **Recipe 12.8 (Disease Progression Trajectory Modeling):** Per-patient long-horizon forecasting that shares the calibration and scenario-forecasting machinery used here at the population level.
- **Recipe 12.4 (Lab Result Trend Analysis):** Per-patient lab trajectory tracking; the chronic-trend-detection patterns extend conceptually to population-level signal-trajectory tracking in this recipe.
- **Recipe 13.x (Knowledge Graphs and Ontology):** Pathogen taxonomies, ICD-10-coded condition hierarchies, and surveillance-system metadata live in the broader clinical-terminology infrastructure covered there.
- **Recipe 14.x (Optimization):** Resource allocation problems (PPE distribution, vaccine-clinic siting, ventilator allocation) that consume epidemic forecasts as their primary input.

---

## Tags

`time-series` · `epidemic-forecasting` · `public-health` · `surveillance` · `compartmental-models` · `seir` · `bayesian-hierarchical` · `state-space-models` · `nowcasting` · `wastewater-surveillance` · `syndromic-surveillance` · `ensemble-forecasting` · `weighted-interval-score` · `calibration-monitoring` · `scenario-forecasting` · `respiratory-virus` · `flu` · `rsv` · `sars-cov-2` · `kinesis` · `glue` · `sagemaker` · `step-functions` · `dynamodb` · `aurora` · `quicksight` · `complex` · `production` · `hipaa`

---

*← [Previous: Recipe 12.8 - Disease Progression Trajectory Modeling](chapter12.08-disease-progression-trajectory-modeling) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.10 - Physiological Waveform Analysis →](chapter12.10-physiological-waveform-analysis)*
