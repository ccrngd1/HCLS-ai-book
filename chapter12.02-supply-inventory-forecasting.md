# Recipe 12.2: Supply Inventory Forecasting ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$100-$400 per month for a single facility's SKU portfolio

---

## The Problem

It's a Tuesday afternoon at a 400-bed community hospital. The materials management coordinator just got a call from the OR: they're out of a particular size of surgical staple cartridge, the one the orthopedic surgeons use for a procedure that's on the schedule for tomorrow. The vendor's next-day delivery cutoff is in two hours. She places an emergency order, pays a 35% expedite fee, and adds another data point to the running tally of stockouts she's been keeping all year. Down the hall, a different problem is playing out in the central supply room: there are eighteen months' worth of a respiratory mask still sitting on the shelf from the pandemic-era surge buy that never got drawn down, taking up space and quietly approaching its expiration date.

Both of those scenes happen in the same building, on the same day, in nearly every hospital in the country. Healthcare supply chains run on guesses dressed up as par levels. Someone, usually years ago, set a reorder threshold. Nobody has revisited it. Demand patterns shifted: a surgeon retired and stopped using one device, a new hospitalist group started ordering a different type of central line kit, the flu season hit hard or didn't hit at all. The par levels are still set to the world that existed when they were configured, and the supply chain absorbs the gap between yesterday's assumptions and today's reality through a combination of stockouts, expedited orders, expired inventory, and storage costs.

The numbers behind this are not small. Hospital supply chain spend is typically the second-largest expense category after labor, and a meaningful fraction of it is wasted on either too much inventory or too little. Stockouts can also delay procedures and force clinical workarounds, which is when supply chain becomes a patient safety issue rather than a financial one. The good news, the same news as in Recipe 12.1, is that supply consumption is largely predictable. Most healthcare SKUs have stable demand patterns once you account for case volume, seasonality, and a few known operational drivers. The signal is there. Most hospitals just don't have a systematic way to extract it and turn it into reorder decisions.

When you do extract it, the operational improvements are immediate and quantifiable: stockout rates drop, expedited orders go away, on-hand inventory shrinks (which frees up working capital and shelf space), and the materials management team stops spending its day fighting fires. Nobody throws a party for a 15% reduction in supply chain working capital, but the CFO notices. Let's get into how it works.

---

## The Technology: How Demand Forecasting Actually Works

### What You're Forecasting and Why It's a Time Series Problem

When you boil supply inventory forecasting down, you have a list of stock-keeping units (SKUs), and for each SKU you want to know: how much will we use over the next N days? That's a demand forecasting problem, and demand by day is a time series. The same forecasting machinery that predicts appointment volume in Recipe 12.1 applies here. The math is similar; the data is different; the operational consumers are different.

The vocabulary is worth nailing down before going further:

- **SKU.** A stock-keeping unit. The thing you order and consume. A specific glove size. A specific suture. A specific drug presentation.
- **Demand.** Quantity consumed per unit time. Usually daily for fast-moving items, weekly or monthly for slow movers.
- **Lead time.** Days from when you place an order to when stock arrives. Varies by vendor and item.
- **Reorder point.** The on-hand quantity at which you trigger a new order. Set so that expected demand during the lead time, plus a safety stock buffer, doesn't drive you to zero.
- **Safety stock.** Extra inventory carried to buffer against demand variability and lead-time variability. Set as a function of how bad a stockout is and how much error you can tolerate in the forecast.
- **Service level.** The target probability that you do not stock out during a given replenishment cycle. 95% and 99% are common targets, with the choice driven by clinical importance.

A good supply forecast feeds two operational decisions: when to reorder (the reorder point) and how much to order (the order quantity). Both decisions depend on the forecast and on the variability around it. Point estimates alone do not get you there. You need the distribution of likely demand, not just the most likely value, because the safety stock calculation is fundamentally a probabilistic one.

### Healthcare Supply Demand Has a Distinctive Shape

Generic retail demand forecasting tutorials treat all SKUs the same. Healthcare doesn't work that way. Supply demand in a hospital tends to fall into one of several distinct buckets, and the right forecasting approach depends on which bucket a SKU lives in.

**High-volume, smooth demand.** Examination gloves, alcohol prep pads, IV bags, common drugs. Hundreds or thousands of units per day. Demand looks like a noisy line with weekly seasonality (lower volume on weekends in many specialty clinics, similar or higher in inpatient settings). Easy to forecast. Standard methods work well.

**Medium-volume, seasonally driven demand.** Flu vaccines, allergy medications, certain respiratory supplies. Demand is concentrated in specific seasons. Annual seasonality dominates. You need at least two full years of history to capture the seasonal cycle.

**Low-volume, intermittent demand.** Specialty surgical kits, rare-disease medications, niche devices. Maybe a few units a week, sometimes zero for weeks at a time. Classical time-series methods break down here because the noise floor swamps the signal. You need methods built for intermittent demand: Croston's method, the Syntetos-Boylan approximation (SBA), or aggregated forecasting at a higher level (e.g., forecast surgical case volume and multiply by per-case usage).

**Procedure-driven demand.** Implants, surgical staples, cardiology consumables. Demand is a near-direct function of case volume. The right approach often isn't to forecast SKU-level demand directly. It's to forecast case volume by procedure type and apply a usage-per-case multiplier. This is more stable and easier to explain to operations.

**Pandemic and crisis demand.** PPE, ventilator consumables, certain pharmaceuticals. The demand history during a public health emergency is not representative of normal operations and should not be used to set normal-operations par levels. Production systems need an explicit way to handle these regime breaks (more on this in the limitations section).

A capable supply forecasting pipeline doesn't try to apply one method to every SKU. It segments the SKU portfolio by demand pattern and routes each segment to the method that fits.

### The Methods That Actually Work

Three method families cover the bulk of practical hospital supply forecasting.

**Classical statistical methods (ETS, ARIMA, SARIMA).** Same family of methods covered in Recipe 12.1. ETS (exponential smoothing, including Holt-Winters) decomposes a series into level, trend, and seasonal components and updates each as new data arrives. ARIMA models series as a function of past values and past forecast errors. Both work well for high-volume, smooth-demand SKUs and are fast to fit. They struggle on intermittent demand because they assume a continuous error distribution.

**Intermittent-demand methods (Croston, SBA, TSB).** Croston's method, developed in the 1970s and still in heavy use, decomposes intermittent demand into two pieces: the demand size when a non-zero demand occurs, and the inter-arrival time between non-zero demands. It forecasts each piece separately and combines them. The Syntetos-Boylan approximation (SBA) is a less-biased variant that's now considered the better default. Teunter, Syntetos, and Babai (TSB) handles obsolescence (a SKU whose demand has stopped) better than either. These methods are essential for the long tail of low-volume hospital SKUs.

**Modern decomposition and ML methods (Prophet, DeepAR, N-BEATS).** [Prophet](https://facebook.github.io/prophet/) is a curve-fitting framework that handles trend, multiple seasonalities, holidays, and special events with minimal tuning. It is forgiving of missing data and produces reasonable prediction intervals out of the box. For high-volume SKUs with multiple overlapping seasonalities, it's a strong default. For multi-SKU problems with hundreds or thousands of related series, neural methods like Amazon's [DeepAR](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html) (a SageMaker built-in algorithm) learn shared patterns across SKUs and can outperform per-SKU classical models, especially for SKUs with limited history.

For most hospital systems, a sensible starting architecture combines two of these: Prophet or ETS for the bulk of high- and medium-volume SKUs, and Croston/SBA for intermittent items. DeepAR comes into play once you're forecasting at scale across many facilities and want a single shared model.

### The Reorder Point and Safety Stock Calculation

The forecast is not the end of the pipeline. Operations needs reorder triggers, not just point predictions. The classical formula, which you'll see implemented in roughly every materials management system on earth, is:

```text
reorder_point = (mean_daily_demand * lead_time_days)
              + safety_stock
safety_stock  = z_score * sqrt(lead_time_days) * std_daily_demand
```

The `z_score` is set by the target service level (1.65 for 95%, 2.33 for 99%). The standard deviation of daily demand comes out of your forecast model: a Prophet prediction interval, a Croston demand-size standard deviation, or whatever the chosen model produces. The lead time has its own distribution and ideally feeds into the calculation as a random variable too, but most production systems start with a fixed lead time per vendor and refine later.

The point worth internalizing: the safety stock calculation depends on the *variability* of the forecast as much as the point estimate. A good forecast that says "demand is steady at 100 units per day, plus or minus 5" produces a much lower reorder point than a model that says "demand is 100 units per day, plus or minus 40." If your forecasts get tighter (lower variance), your inventory levels drop without any change in service level. That's the lever the forecasting work pulls.

### Why This Is Harder Than It Looks

The honest list of things that humble supply forecasting projects:

**SKU explosion.** A medium-sized hospital tracks 5,000 to 15,000 SKUs. A health system tracks ten times that. You can't lovingly hand-tune a model for each one. The pipeline has to do automated segmentation, model selection, and quality gating across the whole catalog.

**Substitution and equivalent items.** Operationally, three different vendors' alcohol prep pads are interchangeable. In the item master, they're three SKUs with three separate demand histories. If you forecast each independently, you'll over-buy. If you collapse them, you have to keep track of which substitution is happening when. Rolling up to "consumption groups" or "GMDN families" is a common compromise.

**Vendor and contract changes.** A new GPO contract changes prices, item codes, or preferred vendors. Suddenly the historical SKU stops being purchased and a new SKU appears. The new SKU has zero demand history. Your model knows nothing. Cold-start handling for SKU substitutions is a real production concern.

**Lead time variability.** "The vendor says 5 days" is what the contract says. The actual delivered lead time, especially during disruptions, is highly variable. A safety stock model that assumes fixed lead times under-buffers exactly when buffering matters most.

**Recall and discontinuation events.** A medical device gets recalled. A drug becomes unavailable. The demand goes to zero overnight, and the forecast has to know not to predict the historical pattern. Operationally, these events have to flow into the pipeline as explicit signals.

**Lumpy procedure demand.** Surgical case mix changes affect implant and instrument demand directly. If you ignore the surgical schedule and only model historical SKU demand, you'll miss the volume change three weeks before it shows up in the time series.

**Expiration dating.** Many supplies have expiration dates. A perfectly accurate annual demand forecast that produces a one-time delivery at the start of the year is wrong if half the items expire before consumption. The order quantity calculation has to respect shelf life, which means tighter, smaller, more frequent orders for short-dated items.

**Pandemic and disaster demand.** Emergency surge consumption is not normal demand. Including the surge period in training data trains your model to over-buy. Excluding it without explicit handling means you have a gap in the data. Production systems mark these periods as exogenous regime breaks and either exclude or down-weight them.

The reassuring news: a basic pipeline that segments SKUs by demand pattern, fits the right model family per segment, and produces reorder-point updates on a weekly or monthly cadence routinely delivers single-digit-percent reductions in stockouts and double-digit-percent reductions in on-hand inventory. The infrastructure is the hard part. The forecasting itself is well-understood.

### The General Architecture Pattern

At a conceptual level, the pipeline looks like this:

```text
[Consumption History] -> [Feature Engineering & SKU Segmentation] ->
[Per-Segment Model Training] -> [Forecast & Reorder Point Calculation] ->
[Materials Management / ERP Integration]
```

**Consumption History.** Daily SKU-level usage extracted from the materials management system, the inpatient pharmacy system, the OR case-cart system, or whichever source-of-truth tracks consumption. Two to three years is the practical minimum to capture annual seasonality. For procedure-driven SKUs, you also need historical case data linked to consumption.

**Feature Engineering and SKU Segmentation.** Two parallel jobs. Feature engineering attaches calendar features (day of week, holiday flags), facility features (location, service line), and exogenous drivers (forecasted case volume, season indicators). SKU segmentation classifies each SKU by demand pattern (smooth, intermittent, lumpy, procedure-driven) using metrics like the average demand interval (ADI) and the coefficient of variation squared (CV²). The classification routes each SKU to the appropriate model family.

**Per-Segment Model Training.** Smooth and seasonal SKUs go through ETS, SARIMA, or Prophet. Intermittent SKUs go through Croston/SBA/TSB. Procedure-driven SKUs go through a two-stage model: forecast cases, multiply by per-case usage. Each model is evaluated on a holdout window using error metrics appropriate for its pattern (MAPE for smooth series, mean absolute scaled error or MASE for intermittent series, since MAPE blows up on zeros).

**Forecast and Reorder Point Calculation.** Trained models produce point forecasts and prediction intervals over the operational horizon (typically 30 to 90 days). The forecast variance feeds into the safety stock formula along with each SKU's lead time and target service level to produce updated reorder points and order quantities.

**Materials Management / ERP Integration.** The reorder points and forecasts get written back to the materials management system, the ERP, or a procurement-facing dashboard. The integration point is usually a structured table or API that downstream systems can query. Nobody operationalizes a Jupyter notebook; in healthcare, the consumer is usually an Oracle, SAP, Workday, or Infor module.

That's the whole concept. History, segmentation, model, reorder point, deliver. The implementation specifics live below.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter12.02-architecture). The Python example is linked from there.

## The Honest Take

The model selection question gets way more attention than it deserves. As with appointment forecasting, Prophet, ETS, and SARIMA are within a few percentage points of each other on the smooth SKUs that drive most of your inventory dollars. The hard work is in the segmentation logic and the master-data plumbing. Spend your time there.

The thing that surprised me the first time I built one of these: the value isn't in the forecast itself, it's in the reorder point updates. Materials managers don't sit around looking at forecasts. They live and die by par levels. If the pipeline produces beautiful forecasts but doesn't translate them into updated reorder points that flow into the ERP, you've built a research project, not an operational system. Invest disproportionately in the integration layer.

Intermittent demand is genuinely harder than the smooth case. Don't underestimate the long tail of slow-moving SKUs. They aren't where most of your inventory dollars sit, but they're where stockouts hurt the most clinically. The smooth high-volume SKUs almost forecast themselves; the intermittent specialty items are where domain knowledge plus the right method (Croston/SBA) plus segmentation routing actually earns its keep.

Concept drift is silent and constant. Surgeons change preferences. Vendors change. Contracts change. New devices enter the formulary. Without monitoring and regular retraining, a pipeline that worked beautifully for a year quietly becomes wrong over the next year. The cost of catching it in week three is two weeks of bad reorder decisions; the cost of catching it in month six is a year of stockouts and over-buys that nobody traced back to the model.

The part that's genuinely hard to communicate to operations: the prediction interval, not the point estimate, is the operational primitive. Materials managers want to ask "what's the worst plausible demand over my lead time so I don't run out?" not "what's the expected demand?" Build the user interface around the upper bound of the interval and the safety stock that backs it out, not the mean. The mean is an interesting summary statistic; the interval is what informs the order.

---

## Related Recipes

- **Recipe 12.1 (Appointment Volume Forecasting):** Uses the same forecasting machinery for ambulatory volume. The supply forecast for procedure-driven SKUs depends on the underlying case forecast.
- **Recipe 12.5 (Hospital Census Forecasting):** Drives demand for inpatient consumables (linens, room kits, certain medications) via the inpatient day forecast.
- **Recipe 14.3 (Inventory Reorder Optimization):** Consumes the forecast and reorder points produced by this recipe and applies a more sophisticated optimization layer (multi-echelon, newsvendor) on top.
- **Recipe 14.10 (Health System Network Design):** For multi-facility systems, the supply forecast plus the network design optimization decides where to hold inventory across the system.
- **Recipe 7.1 (Appointment No-Show Prediction):** For procedure-driven SKUs in clinic settings, the no-show-adjusted case forecast feeds into supply consumption more accurately than the booked-case forecast.

---

## Tags

`time-series` · `forecasting` · `prophet` · `croston` · `sba` · `deepar` · `sagemaker` · `glue` · `dynamodb` · `step-functions` · `supply-chain` · `inventory` · `reorder-point` · `safety-stock` · `simple` · `mvp` · `hipaa`

---

*← [Recipe 12.1: Appointment Volume Forecasting](chapter12.01-appointment-volume-forecasting) · [Chapter 12 Index](chapter12-preface) · [Next: Recipe 12.3 - ED Arrival Forecasting →](chapter12.03-ed-arrival-forecasting)*
