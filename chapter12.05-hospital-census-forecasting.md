# Recipe 12.5: Hospital Census Forecasting ⭐⭐⭐

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$400-$1,800 per month per hospital workload

---

## The Problem

It's 06:30 on a Monday at a 412-bed community hospital. The bed huddle has just started. The house supervisor is reading off the census from a printed report that captured the state of the hospital at midnight. Five and a half hours ago. Since then, the ED admitted nine patients overnight, three more are being held in ED beds waiting for a floor assignment, the cath lab has two procedures starting at 07:00 that will need step-down beds by 11:00, and PACU is holding a post-op orthopedic case who needs a med-surg bed in the next hour. Discharge planning thinks today's discharge volume will be "around 38 to 42, maybe a little less because Dr. Patel is on vacation," which is the kind of guess that ends with the chief operating officer asking, at 16:00, why nobody saw the bed crisis coming.

The hospital is going to be operationally tight today. Some of that tightness was knowable. Some of it is genuinely random. The mix is exactly the part that nobody at the bed huddle has a systematic way to separate. The house supervisor has thirty years of pattern recognition baked into their bones, and they will get the day mostly right by feel. They will also be wrong in costly ways, twice a week, in ways nobody can quite forensically reconstruct after the fact, because the hospital does not actually have a forecast it tracks against. It has a midnight snapshot, a census report that updates every two hours, and a printed sheet that the house supervisor annotates in pencil between phone calls.

Every hospital with more than two hundred beds plays out some version of this scene every morning. The bed huddle is the central nervous system for inpatient operations, and it runs on three things: the current census (now), the past few days of census trends (last week), and the team's collective intuition about what today will look like (vibes). Discharges are the lever everyone tries to pull (case management runs the discharge list, hospitalists round earlier, social work expedites SNF placements). Admissions are the demand they try to absorb (ED holds, direct admits, scheduled surgical admits, transfers from outside facilities). The transfer center makes accept-or-divert decisions based on bed availability that won't actually exist until somebody discharges. The OR schedule for tomorrow gets locked in based on assumptions about bed availability tonight. The medical informatics team has been asked, three times in the last two years, to produce a "real-time bed forecast." Each time the project has stalled because the data is messy, the operational decisions are political, and the existing reporting solution is "good enough."

The cost of getting this wrong shows up in places nobody attributes back to the bed forecast. ED boarding hours (a patient admitted but stuck in an ED bed for hours waiting for a floor bed) are the canonical metric: every hour of boarding correlates with worse outcomes, longer total length of stay, and higher per-stay cost. Diversions ([ambulances rerouted to other hospitals because yours is on bypass](https://www.cms.gov/Medicare/Provider-Enrollment-and-Certification/QAPI/Downloads/Bed-Capacity-and-Diversion-Calculations.pdf)) cost revenue and damage community-trust relationships. Cancelled elective surgeries cost both revenue and patient goodwill. Transferred-out patients (sent to a tertiary center because your hospital had no bed) cost both. Travel-nurse premium pay for the unit that was chronically tight costs the CFO's quarterly margin. Nobody has a single line item on the P&L called "bed forecasting failures," but the cost is real and large, and it is the kind of cost that operations people can describe in ten minutes if you ask them about a recent bad week.

The promise of hospital census forecasting is straightforward: take the data the hospital already has (admissions stream, ED boarders, scheduled surgical admits, transfers, discharge dispositions, average length of stay by service line, hospitalist staffing patterns) and produce an hour-by-hour, unit-by-unit forecast of bed occupancy for the next 4 to 72 hours. Pair that forecast with explicit prediction intervals so the bed huddle knows the difference between "we are confidently going to be tight on telemetry tonight" and "there is a 25% chance we hit gridlock by 22:00." Refresh the forecast as the day progresses and as new data lands (every admission, every discharge, every cancelled surgery, every transfer accepted or declined). Surface the forecast to the bed huddle at 06:30, to the transfer center continuously, to the OR schedulers the night before, and to the ED charge nurse when they're considering whether to call diversion. Get this right and the hospital makes better decisions in real time, and the savings show up in the metrics that matter (boarding hours, diversion hours, cancelled-case rate, premium-labor spend) without anybody having to point at the forecast as the reason.

Let's get into how this works.

---

## The Technology: How Hospital Census Forecasting Actually Works

### Why This Is a Flow Problem, Not a Volume Problem

The first reflex when you hear "predict bed occupancy" is to reach for a generic time-series forecaster and aim it at historical census numbers. That works on day one and breaks within a quarter. The reason: hospital census is fundamentally a flow problem. Today's census is yesterday's census, plus admissions over the last 24 hours, minus discharges over the last 24 hours, plus or minus transfers (in from other facilities, out to SNF, internal between units). The aggregate level is the result of three separate streams interacting, and each stream has its own dynamics, its own drivers, and its own predictability characteristics.

Treat census as one time series and you fit a model that has no awareness of the underlying dynamics. It will learn the seasonal pattern (Mondays trend higher than Sundays) but it will struggle when the dynamics shift. A change in average length of stay (because the hospital launched a new discharge initiative, or because the case mix shifted, or because skilled nursing facility availability collapsed in your region) breaks the model in ways the historical census numbers do not anticipate. A change in admission patterns (because a competing hospital closed, because flu season started two weeks early, because a referring practice was acquired) similarly breaks it.

The right framing is to forecast each flow separately and then compose them. Admissions become one forecast (volume by hour by unit, by source: ED, direct admit, surgical, transfer-in). Discharges become a second forecast (volume by hour by unit, by disposition: home, SNF, rehab, hospice, expired). Length of stay becomes a third forecast or, more often, a survival-style model that says "for each currently-admitted patient, what's the probability they discharge in the next H hours." Transfers (between units, between facilities) become a fourth flow. Census is the integral of these flows over a starting point. Get the flows right and the census forecast is the bookkeeping that follows.

### The Three-Layer Architecture That Actually Works

A capable hospital census pipeline has three conceptual layers that mirror the flow framing.

**Layer 1: Inflow forecasting.** Predict admissions over the forecast horizon, broken down by admission source and admitting service. The pipeline maintains separate sub-models for each source because each has wildly different predictability:

*ED admissions* are the largest source for most hospitals (60 to 75% of admissions in community hospitals, lower in academic centers). They follow patterns similar to ED arrivals (Recipe 12.3), with the additional layer of admit-rate variability. About 12 to 18% of ED visits become admissions in a typical community ED, but the rate fluctuates with case-mix, season, and ED capacity itself. Forecast volume by ED arrival rate times admit rate, both modeled with the calendar and weather features from Recipe 12.3.

*Scheduled surgical admissions* are the most predictable inflow because they're literally on a calendar. Tomorrow's OR schedule produces a deterministic count of inpatient post-op admits for the next 24 to 48 hours, with high reliability. The only uncertainty is no-show rate (typically 2 to 5%) and case-cancellation rate (5 to 12% on the day-of, depending on hospital). Forecast: pull the OR schedule, multiply by the historical show-rate, attribute to the appropriate post-op unit.

*Direct admissions* (admitted from a physician office or clinic without going through the ED) are smaller volume but harder to forecast because the lead time is short (often hours, not days) and the demand is bursty. A fall-day spike in direct admits to ortho is hard to anticipate from yesterday's pattern. Most hospitals model these as a Poisson process with day-of-week and seasonality features.

*Transfers in* (from outside facilities or affiliated hospitals) flow through the transfer center. The transfer center has visibility into pending requests (typically a few hours of lead time) and can supply that as a feature. Most pipelines treat near-term transfers as a known quantity from the transfer center queue and longer-horizon transfers as a forecast.

**Layer 2: Outflow and length-of-stay modeling.** Predict discharges over the forecast horizon, which is the harder of the two flows. Discharges have two characteristics that make them hard:

*The discharge process is partly clinical, partly operational, and partly social.* A patient is medically ready to discharge when the attending says so, which is mostly clinical. They actually discharge when the discharge order is in, the medications are reconciled, the transportation is arranged, and the receiving facility (if any) accepts. That second leg is operational and social. A patient who is medically ready at 09:00 may not actually leave the hospital until 17:00 because of insurance authorization, SNF bed availability, or family transportation. The forecast has to capture both the medical-readiness signal and the operational-completion timing.

*Discharges concentrate during the day.* A typical hospital discharges 70 to 80% of its volume between 10:00 and 18:00, with a strong peak around 13:00 to 15:00. Overnight discharges are minimal. The intra-day pattern is sharp and matters operationally: the bed huddle at 06:30 needs to know how many discharges are projected by 14:00 specifically, not just "by end of day."

The standard approach for discharge forecasting is a survival-style model. For each currently-admitted patient, predict the probability they discharge in the next H hours, conditional on their length of stay so far, their service line, their disposition plan (if known), and dozens of other features. Sum the probabilities to get the expected discharge count. The advantage of this framing over a plain count-forecasting approach: it naturally incorporates patient-level information (a patient on day 6 of an exacerbation admission has different discharge dynamics than a patient on day 1 of a planned surgical admission) and it makes the discharge prediction a per-patient question, which is exactly what the case manager working the unit needs anyway.

The features that matter for the survival model: service line, primary diagnosis (or DRG, once the working DRG is assigned), age, length of stay so far, day of week, hour of day, attending hospitalist, planned disposition (home, SNF, rehab, hospice), [Hospital Acquired Condition](https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/HospitalAcqCond) flags, recent vital sign trajectory, recent lab abnormalities, pending consults, and whether a discharge order has been written. The last feature is the strongest single predictor: "discharge order entered" raises the probability of discharge in the next 6 hours from a baseline of around 8 to 15% to typically 75 to 90%.

**Layer 3: Census composition and unit assignment.** Compose the inflows, outflows, and current state into a unit-level census forecast. This is conceptually simple bookkeeping:

```text
projected_census(unit, t+h) = current_census(unit, t)
                              + projected_admissions_to_unit(unit, t, t+h)
                              + projected_internal_transfers_in(unit, t, t+h)
                              - projected_discharges_from_unit(unit, t, t+h)
                              - projected_internal_transfers_out(unit, t, t+h)
                              ± uncertainty
```

The hard part is unit assignment. A patient admitted from the ED with a chest pain rule-out goes to telemetry, not med-surg. A post-op total knee goes to ortho, not general surgery. A patient who was on CCU but is being downgraded goes to step-down, not back to cath lab. The unit-assignment logic depends on diagnosis, surgical type, attending preference, current unit availability, and the hospital's bed-management protocols. Most pipelines model this as a multinomial classifier per admission source: given the admission's features (diagnosis, surgery type, ED disposition), predict the probability distribution over candidate units.

The output of Layer 3 is the unit-level census forecast: for each unit, for each hour over the forecast horizon, the expected occupancy and a prediction interval. The aggregate hospital census is the sum across units, but the unit-level breakdown is what operations actually consume.

### What Makes Census Different From Other Forecasts

Several characteristics distinguish hospital census forecasting from other time-series problems and shape the methods that work.

**Forecasts have to compose with current state.** The forecast is anchored on the current census, which is itself a moving target throughout the day. Every admission and discharge updates the starting point for the rest of the forecast. The pipeline has to update incrementally, not produce a one-shot daily forecast that goes stale by 09:00. Most production systems re-run inference every 15 to 60 minutes, with the inflow and outflow models taking the latest known state as input.

**Forecast horizon and operational use are tightly coupled.** Different operational decisions live at different horizons:
- 1 to 4 hours: ED diversion decisions, transfer-center accept/decline, OR add-ons
- 4 to 12 hours: same-shift staffing pulls, discharge expediting, internal transfer prioritization
- 12 to 24 hours: next-shift staffing, OR schedule adjustments, surge-plan activation
- 24 to 72 hours: tomorrow's bed plan, OR booking decisions, transfer-in capacity commitments
- 72 hours to 7 days: weekly staffing, scheduled procedure planning

A single model is rarely best across all horizons. Short-horizon forecasts benefit most from current-state features (ED holds, post-op pipeline, pending discharges). Longer-horizon forecasts depend more on calendar and seasonality features. Production pipelines either fit horizon-specific models or use a single model with horizon-dependent feature weighting.

**Units are not independent.** Telemetry being full means new admissions cascade to overflow units. CCU being full means step-down patients can't transfer up. The bed-management protocols define a graph of unit-to-unit overflow rules, and the forecast has to respect them or it produces unit-level numbers that don't add up to a coherent hospital plan. Most teams handle this by forecasting each unit independently and then running a post-processing pass that respects the overflow rules and produces a constrained joint forecast.

**Length of stay is the most operationally actionable input.** A 0.3-day reduction in average LOS frees up roughly 8% of bed-hours in a 412-bed hospital. The forecast has to be sensitive enough to detect when LOS is shifting and surface that to the leadership who can act on it. A pipeline that forecasts census without ever exposing the LOS assumption is missing the operational lever the bed huddle most wants to pull.

**The data is mostly timestamped, but timestamps are not always trustworthy.** ADT (admit-discharge-transfer) messages timestamp every state change in the patient's hospital journey. In theory, you can reconstruct the entire hospital flow from ADT history. In practice, ADT timestamps are sometimes wrong (the discharge timestamp captures when the discharge order was entered, not when the patient left the bed; the transfer timestamp captures when the patient was assigned to the new unit, not when they actually moved). Production pipelines clean and reconcile timestamps against secondary signals (bed-cleaning logs, EHR location updates, telemetry leads detached) and treat the cleaned version as authoritative. Skipping this work produces a forecast trained on noisy timestamps that is calibrated to the noise rather than to the underlying flow.

### Methods That Earn Their Keep

For each of the three layers, a small number of methods consistently work in production.

**For inflow forecasting (Layer 1):** The same toolbox as Recipe 12.3 (ED arrivals) plus deterministic schedule integration for surgical admits. Poisson regression with calendar and weather features handles ED-driven admissions. Multinomial classifiers handle service-line and unit assignment. The OR schedule is read directly. Direct admits and transfer requests use simple Poisson models with day-of-week features.

**For outflow forecasting (Layer 2):** Survival models (Cox proportional hazards, accelerated failure time, gradient-boosted survival models like XGBSE, or deep survival models like DeepHit) on per-patient features. The patient-level approach is more accurate and more operationally useful than aggregate count forecasting. Output: per-patient discharge probability over the forecast horizon, summed for unit-level expected discharges. State-space methods (per-service LOS distributions updated as new discharges arrive) are a simpler alternative when patient-level features are sparse.

**For census composition (Layer 3):** Bookkeeping plus Monte Carlo. Sample N times from each component distribution (admissions, discharges, transfers), compose the census trajectory for each sample, take the mean and percentiles across samples. This naturally produces calibrated prediction intervals. A hospital with thousands of patient-state combinations runs this comfortably with N=500 to 1000 samples; per-unit calibration improves with more samples but with diminishing returns past 1000.

**For real-time updating:** Particle filters or sequential Monte Carlo methods are theoretically elegant but operationally heavy. The simpler approach is to re-run the full pipeline every 15 to 60 minutes with the latest state and let the new forecast supersede the old. The marginal cost of compute is low compared to the operational complexity of online filtering.

### The General Architecture Pattern

At a conceptual level, the pipeline looks like this:

```text
[ADT Stream]
[OR Schedule]                    +---------------------+    +--------------------+    +---------------------+
[Transfer Center Queue]   ---->  | Inflow Forecasting  |    | Outflow / LOS      |    | Census Composition  |
[ED Tracking Board]              | (per source, per    |    | Modeling           |    | (Monte Carlo on     |
[EHR Patient State]              |  service, per unit) |    | (per-patient       |    |  inflows + outflows |
                                 |                     |    |  survival model)   |    |  + current state)   |
                                 +---------------------+    +--------------------+    +---------------------+
                                          |                          |                          |
                                          +---------+----------------+--------------------------+
                                                    |
                                                    v
                                          +---------------------+
                                          | Forecast Repository |
                                          | (per-unit, per-hour |
                                          |  occupancy + intervals)
                                          +---------------------+
                                                    |
                                                    v
                                          +---------------------+
                                          | Operational         |
                                          | Consumers           |
                                          | (Bed Huddle, Transfer
                                          |  Center, OR, ED)    |
                                          +---------------------+
```

**ADT Stream.** Every hospital state change (admission, discharge, transfer, room change, status change) emits an HL7 ADT message or its FHIR Encounter equivalent. The pipeline ingests these in near real time and maintains a current-state view of every occupied bed.

**OR Schedule, Transfer Center Queue, ED Tracking Board.** Three known-quantity feeds. The OR schedule for the next 48 hours is a deterministic input. The transfer center queue is a near-term-known input (1 to 6 hours of lead time). The ED tracking board provides current ED census, holds, and admitted-but-not-yet-placed patients.

**EHR Patient State.** Per-patient features needed by the survival model: service, attending, working DRG (if available), discharge order status, planned disposition, length of stay so far, age, comorbidities. This is typically pulled from the EHR via FHIR API or a clinical data warehouse mirror, refreshed on the same cadence as the forecast.

**Inflow Forecasting.** Per-source, per-service, per-unit admission forecasts. Models trained on historical ADT plus feeds. Refreshed weekly or when drift is detected.

**Outflow / LOS Modeling.** Per-patient discharge probability over the forecast horizon. Survival model trained on historical encounters with feature engineering on patient state at each prediction time. Refreshed monthly or quarterly.

**Census Composition.** Monte Carlo simulation of the census trajectory. Takes the inflow forecasts, the outflow probabilities, and the current state as inputs. Produces per-unit, per-hour expected occupancy plus prediction intervals.

**Forecast Repository.** The output table: (unit, forecast_for_timestamp, expected_occupancy, lower_bound, upper_bound, generated_at_timestamp). Every consumer reads from this.

**Operational Consumers.** The bed huddle dashboard, the transfer center decision support, the OR scheduler, the ED diversion-decision tool, and the staffing scheduler all consume the same forecast. The integration is structured (REST API or query against the forecast store) and the latency budget is single-digit seconds.

That's the whole concept. Three flows, composed into a unit-level census, refreshed continuously, surfaced everywhere. The hard parts are in the data plumbing (ADT cleanup, unit-assignment logic, length-of-stay feature engineering) and in the operational integration, not in the forecasting math.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter12.05-architecture). The Python example is linked from there.

## The Honest Take

The forecasting math is the easy part of this. I have built two of these and the modeling has consistently been the smallest fraction of the engineering investment. The hard parts are upstream (ADT cleanup, length-of-stay feature engineering, unit-assignment ground truth) and downstream (operational integration, feedback capture, narrative explanation). A team that allocates 50% of the budget to data plumbing, 20% to modeling, and 30% to operational integration is closer to the right ratio than the typical "70% modeling, 30% the rest" assumption people walk in with.

The thing that surprised me the first time was how much of the forecast accuracy comes from the discharge order signal. The single feature "has a discharge order been entered for this patient" carries more predictive power for the next-6-hours discharge probability than every other feature combined. A naive model that uses only this feature, with no calendar features, no service line, no LOS, and no demographics, beats a sophisticated model trained without the discharge order. The lesson is not that the other features don't matter; they matter for longer horizons and for patients without orders. The lesson is that the operational reality of how hospitals actually discharge patients is captured in a single binary signal that lots of teams overlook because it feels too simple.

Alert fatigue and dashboard fatigue are real failure modes for census forecasting too. A bed huddle dashboard that shows projections every 15 minutes, with green/yellow/red bands, gets glanced at for two weeks and then ignored. The dashboard has to surface the actionable signal, not the raw projection. "Telemetry will be at 94% by 14:00 with p90 of 29 (capacity 28)" is interesting. "Recommend prioritizing the 2 medically-ready discharges currently held for SNF placement to free capacity before the 13:00 OR turnover" is actionable. The narrative-summary layer is not optional for adoption; it's the difference between a tool the bed huddle uses and a tool they tolerate.

The thing I underestimated, repeatedly, is the political dimension of unit-assignment ground truth. The hospital's bed map looks clean on paper. In reality, the assignment of patients to units is a negotiation between attending preference, charge nurse judgment, current capacity, and historical practice. The unit-assignment classifier trained on historical data captures this negotiation faithfully, including its inconsistencies. When the forecast disagrees with what the bed huddle thinks should happen, the right answer is sometimes "the forecast is correctly capturing what historically happened" and sometimes "the historical pattern was suboptimal and the bed huddle wants to change it." Disambiguating these cases requires conversations with the bed-management team that nobody scopes into the project plan but everyone has to have eventually.

The part that took me the longest to internalize is that this is fundamentally an operational research project wearing a forecasting hat. The forecast is the input to a queueing-and-flow system that the hospital is running implicitly. The bed huddle's job is to balance demand against capacity in real time. The forecast helps them do this better. But the optimization problem (which patients to expedite, which transfers to accept, which surgeries to schedule, which units to open) is not solved by the forecast; it's informed by it. A team that understands the forecast as one input among many to a larger operations problem builds something that gets adopted. A team that thinks they're shipping a forecast as the answer ships something that gets bought, deployed, and quietly bypassed.

If I were starting a new hospital census project today, I would do three things differently. First, I would invest in the calibration and feedback infrastructure on day one, not month four. Second, I would build the narrative-summary layer alongside the forecast, not as a phase-two add-on. Third, I would accept from the beginning that the operational integration work is at least as much engineering as the modeling work, and resource accordingly. The teams that get this right are the ones who plan for it. The teams that don't get blindsided.

---

## Related Recipes

- **Recipe 12.1 (Appointment Volume Forecasting):** Outpatient counterpart to this recipe. Shares the calendar-feature engineering and the operational dashboard pattern; differs in clinical context and decision latency.
- **Recipe 12.3 (ED Arrival Forecasting):** The ED arrival forecast feeds into this recipe's inflow model as the input volume, with admit-rate as the conversion factor. The two pipelines often share infrastructure.
- **Recipe 12.4 (Lab Result Trend Analysis):** Adjacent recipe in the time-series chapter. Shares the FHIR-based ingestion pattern and the survival-style modeling for some variants.
- **Recipe 12.6 (Revenue Cycle Cash Flow Forecasting):** Different domain (financial, not operational) but similar structure: forecasting flows that compose into a level (cash on hand, like census). The methods carry over.
- **Recipe 12.7 (Vital Sign Trajectory Monitoring):** The patient-level acute counterpart. Real-time vital-sign trajectories feed into the discharge-readiness signal that the survival model in this recipe consumes.
- **Recipe 14.x (Optimization / Operations Research):** The downstream consumer of census forecasts. Bed assignment, OR scheduling, and staffing optimization all live in that chapter and use the forecast outputs from this recipe as constraint inputs.

---

## Tags

`time-series` · `census-forecasting` · `hospital-operations` · `bed-management` · `survival-analysis` · `monte-carlo` · `poisson-regression` · `xgboost-survival` · `deepar` · `healthlake` · `fhir` · `adt` · `sagemaker` · `dynamodb` · `step-functions` · `medium` · `production` · `hipaa` · `ed-boarding` · `or-scheduling`

---

*← [Previous: Recipe 12.4 - Lab Result Trend Analysis](chapter12.04-lab-result-trend-analysis) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.6 - Revenue Cycle Cash Flow Forecasting →](chapter12.06-revenue-cycle-cash-flow-forecasting)*
