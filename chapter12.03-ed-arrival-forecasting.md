# Recipe 12.3: ED Arrival Forecasting ⭐⭐

**Complexity:** Simple-Medium · **Phase:** MVP+ · **Estimated Cost:** ~$200-$700 per month per ED

---

## The Problem

It's 17:42 on a Wednesday in February at a regional emergency department. The waiting room has thirty-one people in it. Two ambulance bays are full. The charge nurse has been pulling extra staff from the floor for the last hour because what looked like a normal afternoon at noon turned into a freight train of arrivals between 14:00 and 17:00. There were warning signs, if anyone had been looking: a flu surveillance report flagging elevated activity in three surrounding zip codes, a high-school basketball tournament downtown, and a cold front that pushed the wind chill into single digits. The next shift change is in eighteen minutes. The on-call attending physician for the surge protocol just declined because they're already on a different shift tomorrow. Inpatient is at 96% capacity and has been holding the boarders the ED sent up two hours ago.

This scene plays out somewhere in the United States about every fifteen minutes. Emergency departments in this country see roughly 130 million visits per year, distributed across roughly five thousand EDs, almost all of which staff to historical averages plus the lived intuition of senior charge nurses. Some EDs are very good at this, in the sense that the senior nurses have decades of pattern recognition baked into their bones. Others are not. None of them have a clean, systematic answer to the question that should drive every shift planning meeting: how many patients are going to walk through that door over the next four hours, what's their likely acuity mix, and what staffing pattern will absorb them without compromising care?

The cost of being wrong is not abstract. Understaffing produces the headline pathologies of American emergency medicine: long door-to-doctor times, patients leaving without being seen (LWBS rates above 5% are common; I've seen them spike above 12% on bad nights), boarders backing up into hallway beds, and patient safety events that show up in the morbidity-and-mortality conference next month. Overstaffing burns money, frustrates staff who came in for nothing, and trains everyone to ignore the surge plan because it always cried wolf. The decisions are not all equally easy to reverse. Calling in a per-diem nurse two hours into the shift costs a premium and produces resentment. Sending nurses home early because the surge didn't materialize costs goodwill.

The frustrating part, the part that should make this an obvious target for forecasting, is that ED arrivals are surprisingly predictable in aggregate. Yes, individual arrivals are random. But hourly arrival volume has strong daily and weekly patterns, layered seasonal effects (flu season, summer trauma uptick, allergy season), and meaningful exogenous drivers (weather, local events, school-calendar status, regional respiratory virus surveillance, even nearby ED diversions). The signal is there. Most EDs just don't have a systematic way to extract it and turn it into staffing decisions made twelve to twenty-four hours in advance instead of fifteen minutes too late.

When they do extract it, the operational improvements are immediate. Door-to-doctor times come down. LWBS rates drop. Per-diem labor spend shrinks. The charge nurse stops fighting fires for forty hours a month and starts running the department. Nobody throws a parade for a 22% reduction in agency staffing spend or a 1.4-minute reduction in median door-to-doctor time, but the chief medical officer notices, the CFO notices, and the patients who would otherwise have left without being seen quietly get the care they came for.

Let's get into how this works.

---

## The Technology: How ED Arrival Forecasting Actually Works

### Why ED Arrivals Are a Different Beast

If you've read Recipe 12.1, you know the basic time-series forecasting machinery. ED arrivals use the same toolbox, but the data has a few personality traits that change which methods work and what you have to model carefully.

**ED arrivals are count data on a fast clock.** Hourly counts, sometimes every fifteen minutes for trauma centers. The numbers are smaller (a busy community ED might see 8 to 25 arrivals per hour), which means individual hours have more relative variability than daily appointment counts. The Poisson-ish nature of arrivals matters: the variance is roughly proportional to the mean, so methods that assume constant variance need adjustment.

**Patient acuity matters as much as patient count.** A forecast that says "fifteen patients are arriving in the next hour" is operationally useless if you don't know whether those are fifteen ankle sprains or fifteen chest pains. ED resourcing is acuity-driven. The Emergency Severity Index (ESI) classifies arrivals from level 1 (resuscitation, immediate physician needed) to level 5 (routine, can wait). Levels 1 and 2 demand immediate room and physician attention. Levels 4 and 5 can be handled in a fast-track lane with an advanced practice provider. The acuity mix changes throughout the day (high-acuity skews early morning and late evening, low-acuity skews midday) and across seasons. A complete forecast predicts both volume and mix.

**The pattern is genuinely hourly.** Daily appointment volume has weekly cycles and annual seasonality. Hourly ED arrivals have daily cycles (the morning bump, the post-work surge, the late-night quiet), weekly cycles (Mondays and weekends are different), and annual cycles. All three need to be in the model simultaneously. Classical methods that handle a single seasonality break down here. You need methods that handle multiple seasonalities or you need to engineer features that encode them explicitly.

**Exogenous drivers actually drive things.** Weather affects arrivals. Cold fronts push respiratory cases. Heat waves push dehydration and cardiac events. Snowstorms suppress walk-ins and concentrate emergent arrivals. Influenza surveillance from public health agencies leads ED visits by about a week. Local events (a marathon, a concert, a sports tournament) shift arrival patterns. School calendars change the pediatric mix. A serious forecast brings these in as features. A naive one ignores them and inherits all the prediction error they account for.

**The decisions depend on the tail.** A forecast of "expected 17 arrivals next hour" is fine for back-of-the-envelope planning. For staffing decisions in an ED, what you actually need is the upper end of the prediction interval. You staff to absorb the surge, not the average. The 80th or 90th percentile of the hourly arrival distribution is the operational primitive, not the mean. This is true in retail forecasting too, but the consequences in retail are stockouts of socks. The consequences in EDs are patients in hallway beds.

### The Methods That Actually Work

Three families of methods cover most practical ED arrival forecasting.

**Generalized linear models with calendar features (Poisson regression, negative binomial regression).** The simplest serious approach. Treat hourly arrival count as a Poisson (or, if overdispersed, negative binomial) distributed variable, and regress it against a set of features: hour of day, day of week, week of year, holiday flags, weather, lagged values, and so on. These models are fast, interpretable, easy to explain to a medical director, and surprisingly hard to beat on volume forecasting. They naturally produce prediction intervals that respect the count nature of the data. Statsmodels and scikit-learn both implement this directly.

**Classical time-series methods (SARIMA, Holt-Winters with multiple seasonalities, TBATS).** ARIMA and exponential smoothing extend to multiple seasonal periods, but the math gets gnarly. [TBATS](https://otexts.com/fpp3/complexseasonality.html#tbats-models) (Trigonometric, Box-Cox, ARMA, Trend, Seasonal) was designed specifically for series with multiple seasonalities. It handles hourly data with daily, weekly, and annual cycles in one model. It's slower to fit than GLM approaches and harder to extend with exogenous variables, but it's a strong baseline if you have clean history without much in the way of weather or event drivers.

**Modern decomposition and ML methods (Prophet, DeepAR, Temporal Fusion Transformer).** [Prophet](https://facebook.github.io/prophet/) handles multiple seasonalities and holidays gracefully, and it accepts external regressors (weather, flu index, event calendar) as additional inputs. It's a solid pragmatic default for ED hourly forecasting. Amazon's [DeepAR](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html), a SageMaker built-in algorithm, learns jointly across many related series, which earns its keep when you're forecasting across multiple EDs in a health system. Temporal Fusion Transformer (TFT) and similar attention-based models are state-of-the-art on accuracy but require enough history and engineering investment that they rarely win on a single-ED problem.

For a single ED, a sensible starting architecture is a Poisson regression with calendar and weather features for volume, plus a separate multinomial classifier for acuity mix. That gets you 80% of the available accuracy with a model the medical director can interrogate. Prophet is a strong second choice when you have several years of history and want to capture seasonality without engineering all the features by hand. DeepAR makes sense at scale, when you're standing up a forecast across dozens of EDs in a health system and want to share strength across them.

### The Acuity Mix Problem

Forecasting acuity is its own modeling problem on top of the volume forecast. Two reasonable approaches:

**Joint volume-and-mix forecasting.** Forecast the count of arrivals at each ESI level separately. Five Poisson regressions instead of one. Slightly more complex, but each per-acuity model can use its own features (ESI level 1 cardiac arrests have different drivers than ESI level 4 minor complaints). This is the cleaner approach if you have enough data per level.

**Volume forecast plus acuity-mix classifier.** Forecast total volume with one model. Then predict the share of arrivals at each ESI level using a separate multinomial classifier with the same calendar and weather features. Multiply the two to get per-acuity counts. This is more sample-efficient when acuity-level history is sparse (ESI 1 arrivals are rare).

The second approach is usually the practical default. The first is more principled when you have multi-year, high-volume history and need tight per-acuity intervals.

### Why This Is Harder Than It Looks

The honest list of things that humble first-time ED forecasters:

**Walkouts and LWBS distortions.** A patient who arrived at the door, registered, and left without being seen counts as an arrival in some data definitions and not others. If the EHR's arrival timestamp is the registration timestamp, a busy ED that loses patients before registration has a systematic undercount of true demand. This biases your forecast toward what the ED has historically been able to absorb, not what actually showed up at the door. You need an explicit pre-registration arrival capture (often from the front desk swipe-in, the security camera, or a manually-counted log) to break this loop.

**Diversion events.** When the ED goes on diversion (ambulances are routed elsewhere because the ED is overwhelmed), the arrival count drops artificially. A model trained on diversion-affected history under-predicts true demand. Production systems mark diversion windows in the data and either exclude them or model the effect explicitly.

**Acuity drift over time.** ESI level definitions are stable on paper, but the mix of patients seen by an ED can shift over years as urgent care alternatives expand or contract, as the local population changes, and as referral patterns evolve. Models trained on five-year-old data may forecast against a different acuity distribution than the one you have today. Retraining cadence matters more than for ambulatory volume forecasting.

**Holidays and special events.** Christmas, Thanksgiving, the Fourth of July, and New Year's Eve all have distinctive ED arrival patterns. Christmas day is quiet; the day after Christmas is a surge. Memorial Day weekend brings trauma uptick. Naive models miss all of this. The holiday calendar has to encode not just "is this a holiday" but "which holiday and what's the relative day in the holiday window."

**Weather and respiratory virus seasonality.** Weather effects are not linear. A mild cold day might push arrivals slightly; a severe cold day with ice can cut them by 30% (people stay home) or surge them by 50% (slip-and-fall trauma, cardiac events from snow shoveling). Influenza surveillance lags by about a week, so you need historical CDC FluView or local surveillance data integrated as features. None of this is hard, but it's all engineering work that the simplest tutorials skip.

**Forecast horizon and uncertainty.** A 4-hour forecast is dramatically more accurate than a 24-hour forecast. Operational decisions vary in lead time: charge-nurse decisions are made 1 to 4 hours out, shift staffing is set 8 to 24 hours out, schedule planning is made weeks out. Each horizon needs its own model evaluation, and uncertainty grows fast with horizon. Forecasts presented as point estimates are misleading; forecasts with prediction intervals let charge nurses make sensible call-in decisions.

**Boarding and downstream coupling.** ED throughput depends not just on ED arrivals but on the inpatient hospital's ability to admit boarders. When the hospital is at capacity, the ED fills up regardless of arrival rate. A pure arrival forecast misses this. The full operational picture connects to inpatient census forecasting (Recipe 12.5), and the most useful EDs build coupled forecasts that consider both. That's outside the scope of a basic arrival recipe but worth flagging.

The reassuring news: a basic Poisson regression with hour-of-day, day-of-week, holiday, and weather features routinely achieves 10-20% MAPE on hourly volume forecasts at a 4-hour horizon, and 15-30% at a 24-hour horizon. That's accurate enough to make a meaningful difference in staffing decisions. The forecast doesn't have to be perfect to be useful; it just has to be better than the gut feel of a charge nurse who's been on shift for nine hours.

### The General Architecture Pattern

At a conceptual level, the pipeline looks like this:

```text
[ED ADT / Registration Stream] ----> [Feature Engineering & Aggregation] ----> [Volume + Acuity Models] ----> [Forecast Generation] ----> [ED Operational Consumers]
                                          ^                                          ^
                                          |                                          |
                                  [Weather & Surveillance]                  [Retraining Loop]
                                  [Event Calendar]
                                  [Holiday Calendar]
```

**ED ADT / Registration Stream.** Each ED arrival triggers an HL7 ADT-A04 (registration) message or its FHIR equivalent. The pipeline ingests these, captures arrival timestamp, ESI level (if assigned at triage), chief complaint, and basic demographics. For hourly forecasting, the data is bucketed into hourly arrival counts per ESI level. For high-fidelity work, fifteen-minute buckets are common. Two to three years of clean history is the practical minimum.

**Weather and Surveillance.** External feeds: weather data (current and forecast) from a meteorological API, influenza and respiratory virus surveillance from CDC FluView or a state public health feed, an event calendar with local events (sports, concerts, festivals) that affect arrival patterns. The latter is often hand-curated. The former two are programmatic.

**Feature Engineering and Aggregation.** Raw arrival records get aggregated to the hourly grid. Calendar features (hour of day, day of week, week of year, holiday markers) get added. External features (weather variables, flu index, event flags) get joined on. Lagged values (last hour's count, same hour yesterday, same hour last week) get computed. The output is a single tabular dataset where one row equals one (date, hour) pair with the count target and all features.

**Volume + Acuity Models.** Two parallel modeling tracks. The volume track fits a count model (Poisson regression, Prophet, or DeepAR) on hourly total arrivals with all features. The acuity track fits a multinomial classifier predicting the per-ESI-level share of arrivals. Both models hold out a recent window (typically 90 days) for validation. Both produce point forecasts and prediction intervals.

**Forecast Generation.** On a frequent cadence (typically every hour for short-horizon forecasts, every 4 to 6 hours for longer horizons), the trained models produce forecasts at the operational horizons consumers need: 4-hour for charge nurse decisions, 24-hour for shift staffing, 7-day for schedule planning. Each forecast is a count plus a prediction interval, broken out by ESI level.

**ED Operational Consumers.** The forecasts feed into the charge nurse dashboard, the staffing scheduler, the surge plan trigger logic, and the patient flow management system. The integration is usually a structured table or API. The dashboard shows projected arrivals by hour with prediction intervals overlaid on actuals, plus a per-acuity breakdown.

That's the whole concept. Stream, features, model, forecast, deliver. The real complexity is in the feature engineering and the operational integration, not in the modeling itself.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter12.03-architecture). The Python example is linked from there.

## The Honest Take

The model selection question gets way more attention than it deserves. For most ED arrival forecasting problems, a Poisson regression with thoughtful features lands within a few percentage points of Prophet, which lands within a few percentage points of DeepAR. The hard work is in the data quality (clean ADT history, accurate ESI labels, integrated weather feed, maintained event calendar), not in the choice of forecasting algorithm. Spend your time on the data plumbing.

The thing that surprised me the first time I built one of these: the forecast that the charge nurse actually wants is not the volume forecast. It's the answer to "do I need to call someone in?" That question is a function of forecast volume, current census, current acuity mix, current boarder count, current staff level, and the operational definition of "overwhelmed." The forecast is one input. The decision is the integration of all of them. Build the dashboard around the decision, not around the model output.

Acuity is harder than volume. Volume forecasts converge nicely with a few years of history and the right features. Acuity mix is more sensitive to short-term shifts (a flu wave concentrates ESI 3 visits, a heat wave concentrates ESI 2 visits) and the historical training data may not match the immediate present. Building a separate, faster-retraining acuity model that updates more frequently than the volume model is a worthwhile refinement once the basic pipeline is stable.

Concept drift is real and faster than you think. ED catchment areas change as competitors open or close. Local population shifts as housing develops or contracts. Telehealth and urgent care eat into low-acuity walk-in volume; that boundary moves year over year. A model trained on 2023 data and deployed in 2026 will be wrong about the 2026 mix in ways you can't fully predict. Bake monitoring in from day one. The cost of catching drift in week three is two weeks of stale forecasts; the cost of catching it in month six is six months of unexplained operational underperformance.

The part that's genuinely hard to communicate to operations: the prediction interval, not the point estimate, is the operational primitive. ED leaders want to know "what's the worst plausible four-hour window in the next twenty-four hours so I can pre-position staff?" not "what's the expected count for the 18:00 hour?" Build the dashboard around the upper bound of the interval and the surge plan trigger that backs out of it. The mean is interesting; the upper tail is what informs the call-in decision.

---

## Related Recipes

- **Recipe 12.1 (Appointment Volume Forecasting):** The same forecasting machinery applied to lower-variability scheduled visits. Useful as a comparison point and shares the SageMaker training/serving infrastructure.
- **Recipe 12.5 (Hospital Census Forecasting):** Predicts inpatient census, which couples with ED arrivals to drive boarder counts and ED throughput. Most useful when run jointly.
- **Recipe 12.7 (Vital Sign Trajectory Monitoring):** Once patients are in the ED, vital sign monitoring detects deterioration. The ED arrival forecast determines staffing for that monitoring.
- **Recipe 14.2 (Nurse Staffing Optimization):** Consumes the ED arrival forecast as an input to the staffing optimization problem.
- **Recipe 3.10 (Epidemic / Outbreak Detection):** The flu-index and respiratory-virus surveillance signals that feed the arrival forecast also feed outbreak detection. Shared upstream data plumbing.

---

## Tags

`time-series` · `forecasting` · `ed` · `emergency-department` · `arrival-forecasting` · `acuity` · `esi` · `prophet` · `deepar` · `sagemaker` · `kinesis` · `dynamodb` · `step-functions` · `staffing` · `simple-medium` · `mvp` · `hipaa`

---

*← [Previous: Recipe 12.2 - Supply Inventory Forecasting](chapter12.02-supply-inventory-forecasting) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.4 - Lab Result Trend Analysis →](chapter12.04-lab-result-trend-analysis)*
