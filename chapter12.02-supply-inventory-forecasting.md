# Recipe 12.2: Supply Inventory Forecasting ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$100–$400 per month for a single facility's SKU portfolio

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

## The AWS Implementation

The AWS implementation looks a lot like Recipe 12.1's. That's not laziness; it's that the ML platform pieces (managed training, batch inference, scheduled orchestration, low-latency serving) are the same, even when the modeling problem is different. What changes here is the data shape (many SKUs, not one site), the model selection logic (segmentation routing), and the integration target (materials management / ERP, not staffing tools).

### Why These Services

**Amazon SageMaker for model training and inference.** SageMaker is the right home for both classical statistical methods (Prophet, statsmodels, intermittent-demand methods, all installable in a custom container) and the multi-series neural methods like the [DeepAR built-in algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html). For a single-facility forecast across thousands of SKUs, DeepAR's ability to learn jointly across related series is genuinely useful. Amazon Forecast was the obvious choice a few years ago, but AWS [announced its end of availability](https://aws.amazon.com/blogs/machine-learning/transition-your-amazon-forecast-usage-to-amazon-sagemaker-canvas/), and new builds should target SageMaker directly.

<!-- TODO (TechWriter): N1. Verify the Amazon Forecast deprecation status and link as of the publication date. The transition guidance link is current as of mid-2024; check that AWS has not moved or replaced this guidance. -->

**Amazon S3 for consumption data, model artifacts, and forecast outputs.** SKU consumption history (often a substantial dataset for a multi-year, multi-facility extract) lands in S3 partitioned by date and facility. Model artifacts and forecast outputs land back in S3 as the canonical output. S3 with SSE-KMS encryption is the standard durable storage layer.

**AWS Glue for ETL.** Healthcare consumption data often arrives messy: multiple source systems, inconsistent SKU coding, missing days, mixed timezones. Glue ETL jobs (or Glue notebooks for development) handle the cleanup, the joining of SKU master data with consumption transactions, and the writing of the modeling-ready dataset. For Pythonic teams, AWS Glue's PySpark jobs feel familiar; for SQL-heavy teams, Glue's SQL transforms via Athena work too.

**AWS Step Functions for orchestration.** The pipeline has multiple steps with branching logic: extract data, segment SKUs, fan out per-segment training jobs, gather forecasts, calculate reorder points, write back. Step Functions handles the orchestration with explicit retry logic, parallel execution via the Map state for per-segment training, and visibility into each step.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Specify the Step Functions Map-state error-handling contract: per-iteration retry policy (3 retries with exponential backoff on States.TaskFailed and SageMaker.SageMakerException), Catch routing on persistent failure (CloudWatch metric `segment_training_failed`, log to a dedicated log group with segment label and SageMaker job name, route segment-failure record to an SQS DLQ), `ToleratedFailurePercentage` so a small number of segment failures does not abort the pipeline, quality-gate rejection routing (model rejection emits CloudWatch metric, segment falls back to prior production model, SNS notification to ML engineer), and a pipeline-level `partial_failure: true/false` flag with a `failed_segments` list propagated to the downstream reorder-point step (which stamps DynamoDB records with `model_freshness: "current" | "stale"`). Add the DLQ box and SNS topic to the architecture diagram explicitly. -->

**Amazon DynamoDB for serving forecasts and reorder points.** Operational consumers (materials management dashboards, the ERP integration layer) need to query the latest forecast and reorder point for a given SKU at low latency. DynamoDB's key-value access pattern fits perfectly: query by facility-and-SKU, get back the forecast, the prediction interval, the reorder point, and the suggested order quantity.

**Amazon EventBridge for scheduling.** EventBridge Scheduler triggers the pipeline on a weekly cadence. Most hospital materials management cycles run weekly, with daily consumption refreshes feeding the next forecast cycle.

### Architecture Diagram

```mermaid
flowchart LR
    A[Materials Mgmt /<br/>OR / Pharmacy Systems] -->|Daily Export| B[S3 Bucket<br/>consumption-history/]
    M[SKU Master Data]    -->|Daily Refresh| B
    C[EventBridge Schedule<br/>weekly] -->|Trigger| D[Step Functions<br/>forecast-pipeline]
    D -->|Step 1| E1[Glue ETL<br/>Clean & Join]
    D -->|Step 2| E2[Lambda<br/>Segment SKUs]
    E2 -->|Per-Segment Jobs| F[SageMaker Training Jobs<br/>Prophet / Croston / DeepAR]
    F -->|Model Artifacts| G[S3 Bucket<br/>models/]
    D -->|Step 3| H[SageMaker Batch<br/>Forecast Job]
    H -->|Forecasts| I[S3 Bucket<br/>forecasts/]
    I -->|Lambda<br/>Reorder Calc| J[DynamoDB<br/>sku-forecasts]
    J -->|Query API| K[ERP / Materials<br/>Mgmt Dashboard]
    D -->|Errors| L[CloudWatch Alarms<br/>SNS Topic]

    style B fill:#f9f,stroke:#333
    style F fill:#ff9,stroke:#333
    style J fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker, Amazon S3, AWS Glue, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge, AWS Lambda, Amazon CloudWatch |
| **IAM Permissions** | `sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`, `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `states:StartExecution`, `dynamodb:BatchWriteItem`, `kms:Decrypt` |
| **BAA** | AWS BAA signed by default. Hospital consumption data typically carries case-level linkage even when aggregated to daily SKU counts, and PHI-by-association applies. Pure aggregate-SKU-count data with no case-level, patient-level, or procedure-level linkage may fall outside BAA scope, but production systems rarely operate at that level of disconnection. |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest enabled (default); SageMaker training and inference: encrypted EBS volumes, KMS-encrypted output; CloudWatch log groups: configure KMS encryption explicitly. <!-- TODO (TechWriter): Expert review S1 (HIGH). Specify customer-managed KMS keys (CMKs) per data class for blast-radius containment: separate CMKs for consumption-history-and-SKU-master (PHI-by-association), model-artifacts, forecasts-and-DynamoDB serving, SageMaker training output, and CloudWatch log groups. Per-Lambda least-privilege IAM roles scoped to the CMK for that data class only (the reorder-point Lambda has kms:Decrypt on only the forecasts-and-DynamoDB CMK; the training-job role has kms:Decrypt on consumption-history and kms:Encrypt on model-artifacts; cross-class permissions are not granted). --> |
| **VPC** | Production: SageMaker training and inference jobs in VPC with VPC endpoints for S3, CloudWatch Logs, and KMS. Required for HIPAA workloads. <!-- TODO (TechWriter): Expert review N1 (MEDIUM). Enumerate the full VPC endpoint set with endpoint type: gateway endpoints (free, no per-AZ cost) for S3 and DynamoDB; interface endpoints (per-AZ-per-endpoint cost) for SageMaker API, SageMaker Runtime, Step Functions, EventBridge, Glue, Lambda, KMS, CloudWatch Logs, CloudWatch Monitoring, and Secrets Manager (where used for ERP integration credentials). Add TLS 1.2 minimum (TLS 1.3 preferred) at every external boundary per N2 (LOW). --> |
| **CloudTrail** | Enabled: log all SageMaker, S3, DynamoDB, and Glue API calls for HIPAA audit trail. <!-- TODO (TechWriter): Expert review S2 (MEDIUM). Specify CloudTrail data events on the consumption-history, SKU-master, model-artifacts, and forecasts S3 buckets, on the DynamoDB serving table, and on the customer-managed KMS keys (management events alone log resource creation but not GetObject/GetItem reads). Note dedicated logs bucket with Object Lock in compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. --> |
| **Sample Data** | Synthetic SKU consumption data. The [M5 Forecasting Competition dataset](https://www.kaggle.com/competitions/m5-forecasting-accuracy/data) is a useful (retail, not healthcare) public dataset for testing multi-SKU forecasting code. For healthcare-shaped synthetic data, generate from a known process (case volume * per-case usage + smooth consumables + intermittent specialty items + noise) so you can validate the pipeline against ground truth. Never use real consumption data linked to patient identifiers in dev. |
| **Cost Estimate** | SageMaker training (multiple ml.m5.large jobs in parallel via Map state, ~30 min weekly): ~$2/week. SageMaker batch transform: ~$1/week. Glue ETL (~10 min weekly): ~$0.50/week. S3, DynamoDB, Step Functions, Lambda: pennies per day. Total: $100–$400/month for a single facility's SKU portfolio, dominated by SageMaker compute and SKU count. <!-- TODO (TechWriter): Expert review V2 (LOW). Decompose the $100-$400/month range by SKU count and forecast cadence (assumes 5,000-15,000 SKUs and weekly cadence) and clarify how cost scales for multi-facility health-system deployments (approximately linearly with SKU count if per-segment training is decomposed by facility, or sublinearly with SKU count if a shared DeepAR model is used across facilities). --> |

<!-- TODO (TechWriter): V1. Verify SageMaker, Glue, and DynamoDB pricing assumptions reflect current rates. AWS pricing changes; confirm against the AWS pricing calculator before publication. -->

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Trains per-segment forecasting models (Prophet/ETS/Croston/DeepAR) and runs scheduled batch inference |
| **Amazon S3** | Stores consumption history, SKU master data, model artifacts, and forecast outputs |
| **AWS Glue** | ETL jobs to clean consumption data, join with SKU master, fill missing days, write modeling-ready datasets |
| **AWS Step Functions** | Orchestrates the multi-step pipeline (ETL, segmentation, parallel training, inference, reorder calculation) |
| **Amazon EventBridge** | Triggers the pipeline on a weekly schedule |
| **AWS Lambda** | Lightweight transforms: SKU segmentation logic, reorder-point calculation, DynamoDB loader |
| **Amazon DynamoDB** | Serves SKU forecasts and reorder points to operational systems at low latency |
| **AWS KMS** | Manages encryption keys for S3, DynamoDB, Glue, and SageMaker |
| **Amazon CloudWatch** | Logs, metrics, alarms for pipeline failures and forecast drift per SKU segment |

### Code

> **Reference implementations:** The following AWS sample resources demonstrate the patterns used in this recipe:
>
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Official SageMaker examples including DeepAR notebooks for multi-series time-series forecasting
> - [Amazon SageMaker DeepAR Forecasting](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html): Built-in algorithm documentation for DeepAR with example invocations for multi-SKU forecasting
> - [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html): ETL patterns for cleaning and joining transactional data, applicable to consumption history preprocessing

<!-- TODO (TechWriter): N2. Verify all three reference implementation links are still live and up-to-date. -->

#### Walkthrough

**Step 1: Pull and shape the consumption data.** The pipeline starts by extracting daily SKU consumption from the source-of-truth systems: the materials management ledger for general supplies, the OR case-cart system for surgical implants and devices, and the inpatient pharmacy system for medications. Each source has its own data model and identifier scheme. You join them against a unified SKU master so that downstream code sees a single consumption fact table. As with Recipe 12.1, this step is roughly 60% of the work and the place where data quality issues bite hardest. A SKU that gets renamed in the item master mid-history will look like a discontinued product followed by a brand-new product unless you reconcile the change explicitly.

```text
FUNCTION prepare_consumption_data(raw_consumption, sku_master):
    // Collapse raw transactions to daily counts per SKU per facility.
    // The forecasting model expects regular intervals: one row per day per
    // (facility, sku) pair.
    daily_consumption = group raw_consumption by (facility_id, sku_id, date)
                        then sum quantity per group

    // Fill in missing days with explicit zero counts. A missing day is
    // not the same as zero consumption, but for forecasting purposes
    // the safer default is to assume the SKU was available and not used
    // rather than to leave a gap that the model interprets as continuity.
    daily_consumption = fill missing dates with quantity = 0

    // Reconcile SKU renames and merges using the master data. If SKU A
    // was retired and replaced by SKU B on a known date, attribute the
    // pre-cutover history of A to B so the new SKU has continuous history.
    daily_consumption = apply sku_master.successor_map to daily_consumption

    // Add calendar features and exogenous signals.
    FOR each row in daily_consumption:
        row.day_of_week        = day index (0-6) of row.date
        row.month              = month of row.date
        row.is_holiday         = TRUE if row.date is in holiday_calendar
        row.scheduled_cases    = lookup forecasted_cases(facility, date)  // for procedure-driven SKUs
        row.flu_season_index   = seasonal indicator for respiratory SKUs

    RETURN daily_consumption
```

**Step 2: Segment SKUs by demand pattern.** Every SKU does not get the same model. A one-size-fits-all approach over-fits the smooth items and produces nonsense for the intermittent ones. Segmentation classifies each SKU by its consumption pattern and routes it to the appropriate model family. The standard quantitative classification uses two metrics: the average demand interval (ADI), which captures intermittence, and the coefficient of variation squared of demand size (CV²), which captures variability. The four-corner classification produces smooth, intermittent, erratic, and lumpy categories.

```text
FUNCTION segment_skus(daily_consumption):
    segments = empty mapping  // sku_id -> segment_label

    FOR each sku in unique skus(daily_consumption):
        sku_history = filter daily_consumption to sku
        non_zero_days = days where quantity > 0
        all_days      = total days in history

        // Average Demand Interval: average gap between non-zero demand days.
        adi = all_days / count(non_zero_days)

        // Coefficient of Variation Squared on non-zero demand sizes.
        cv2 = (std_dev(non_zero_days.quantity) / mean(non_zero_days.quantity)) ^ 2

        // Standard four-corner classification (Syntetos et al.).
        IF adi <  1.32 AND cv2 <  0.49:  segments[sku] = "smooth"
        IF adi >= 1.32 AND cv2 <  0.49:  segments[sku] = "intermittent"
        IF adi <  1.32 AND cv2 >= 0.49:  segments[sku] = "erratic"
        IF adi >= 1.32 AND cv2 >= 0.49:  segments[sku] = "lumpy"

        // Procedure-driven override: SKUs flagged in the master as
        // implant/instrument types route to a per-case-usage model
        // regardless of demand pattern.
        IF sku.is_procedure_driven: segments[sku] = "procedure_driven"

    RETURN segments
```

**Step 3: Train models per segment.** Each segment gets a training job tuned to its demand pattern. The Step Functions Map state fans out the per-segment training in parallel, which keeps wall-clock time manageable even on a multi-thousand-SKU portfolio. The training step holds out the most recent 90 days as a validation window, fits the segment's chosen model on everything before that, and computes prediction error on the held-out window using a metric appropriate to the segment (MAPE for smooth, MASE for intermittent).

```text
FUNCTION train_segment_model(segment_label, segment_history):
    // Hold out the most recent 90 days of history to evaluate the model
    // against actual outcomes.
    training_data, validation_data = split segment_history at (max_date - 90 days)

    // Pick the model family for this segment.
    SWITCH segment_label:
        CASE "smooth":
            model = fit Prophet on training_data with:
                weekly_seasonality  = TRUE
                yearly_seasonality  = TRUE
                holidays            = holiday_calendar
        CASE "intermittent":
            model = fit Syntetos-Boylan Approximation (SBA) on training_data
        CASE "erratic":
            model = fit Croston's method with smoothing on training_data
        CASE "lumpy":
            // Lumpy SKUs often forecast best in aggregate. Roll up to a
            // category level, forecast there, then disaggregate.
            model = fit hierarchical model at category level
        CASE "procedure_driven":
            // Two-stage: case forecast * per-case usage rate.
            usage_rate = mean(quantity / scheduled_cases) over training_data
            model      = wrap_case_forecast(case_forecast_model, usage_rate)
        CASE "deepar_pool":
            // Optional: pool many smooth SKUs into one DeepAR model
            // to share strength across series.
            model = fit DeepAR via SageMaker on pooled training_data

    // Score on the held-out 90 days and capture forecast variance,
    // because the safety stock formula needs std deviation, not just
    // point predictions.
    forecast = model.predict(dates from validation_data)
    error    = segment_appropriate_error(forecast, validation_data.actual)
    sigma    = std_dev of (forecast.point - validation_data.actual)

    // Quality gate: reject the new model if it materially regresses
    // against the current production model for this segment.
    IF error > current_production_model[segment_label].error * 1.20:
        REJECT this model; alert the ML engineer

    RETURN model, error, sigma
```

**Step 4: Generate forecasts and reorder points.** With trained models in hand, the inference step produces a 30-to-90-day horizon forecast for each SKU and combines the forecast variance with the SKU's lead time and target service level to compute the reorder point and order quantity. This is the operational output. The materials management system consumes these reorder points, not the raw forecasts.

```text
FUNCTION generate_sku_forecasts_and_reorder_points(models, skus, sku_metadata):
    forecast_records = empty list

    FOR each sku in skus:
        model    = models[sku.segment]
        sigma    = model.sigma  // std dev of forecast error
        horizon  = 90 days
        lead     = sku_metadata[sku].lead_time_days
        service  = sku_metadata[sku].target_service_level   // e.g. 0.95

        // Run the model forward over the future dates.
        raw_forecast = model.predict(sku, dates from today+1 for horizon days)

        // Aggregate to lead-time horizon for the reorder calculation.
        mean_demand_during_lead = mean(raw_forecast.point) * lead

        // Safety stock: classical formula. z * sqrt(lead_time) * sigma_daily.
        z_score                   = inverse_normal_cdf(service)
        safety_stock              = z_score * sqrt(lead) * sigma
        reorder_point             = round(mean_demand_during_lead + safety_stock)

        // Suggested order quantity: simple EOQ-style approximation.
        // Production systems plug in real holding-cost and order-cost data.
        order_quantity            = suggest_order_quantity(
            sku, mean_demand_during_lead, sku_metadata[sku].holding_cost,
            sku_metadata[sku].order_cost
        )

        append to forecast_records: {
            facility_id:        sku.facility_id,
            sku_id:             sku.sku_id,
            segment:            sku.segment,
            forecast_date_from: today + 1,
            forecast_horizon:   horizon,
            mean_demand_horizon:round(sum(raw_forecast.point)),
            lower_bound:        round(sum(raw_forecast.lower)),
            upper_bound:        round(sum(raw_forecast.upper)),
            reorder_point:      reorder_point,
            order_quantity:     order_quantity,
            generated_at:       current UTC timestamp,
            model_version:      model.version_id
        }

    RETURN forecast_records
```

**Step 5: Deliver forecasts and reorder points to the materials management system.** The forecast records get written to DynamoDB keyed by facility-and-SKU so the materials management dashboard, the ERP integration job, and any other downstream consumer can query the current values at low latency. As in Recipe 12.1, the write is idempotent: today's forecast for (facility A, SKU B) overwrites yesterday's forecast for the same key.

```text
FUNCTION load_forecasts_to_dynamodb(forecast_records, table_name):
    // DynamoDB BatchWriteItem accepts up to 25 items per call.
    batches = chunk forecast_records into groups of 25

    FOR each batch in batches:
        // Each item is keyed by (facility_id + "#" + sku_id, generated_at)
        // so the latest forecast supersedes prior versions.
        write batch to DynamoDB table_name with:
            partition_key = facility_id + "#" + sku_id
            sort_key      = generated_at
            attributes    = { mean_demand_horizon, lower_bound, upper_bound,
                              reorder_point, order_quantity, segment, model_version }

        IF batch had unprocessed items:
            retry unprocessed items with exponential backoff

    // Optional: also write an aggregate "current" record at sort key
    // "CURRENT" so consumers can do a single GetItem instead of querying
    // by sort key and sorting client-side.
    upsert "CURRENT" record per (facility_id, sku_id) pointing to latest forecast.

    RETURN count of records written
```

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Specify the reorder-point compute decomposition for multi-thousand-SKU portfolios. A 5,000-SKU facility produces 5,000 forecast records that may approach the 15-minute Lambda timeout if implemented naively. Recommended: a Step Functions parallel state with one Lambda invocation per segment, each handling 100-500 SKUs with explicit pagination, BatchWriteItem chunking with retry on UnprocessedItems, and per-Lambda timeout headroom (10-minute Lambda invocations with 15-minute timeout). Update the diagram to decompose "Reorder Calc" into per-segment Lambda invocations under a parallel state. -->

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Specify the idempotency contract for Step 5: the `generated_at` timestamp is computed once at the pipeline-start step (derived from the EventBridge schedule's invocation ID for at-least-once trigger idempotency) and propagated through the Step Functions state, not recomputed per Lambda invocation; the `CURRENT` upsert uses a conditional write `ConditionExpression: attribute_not_exists(generated_at) OR generated_at < :new_generated_at` to prevent stale upserts overwriting newer records; the BatchWriteItem retry on `UnprocessedItems` is bounded (e.g., 5 retries with exponential backoff) and surfaces a metric on the count of unprocessed items. -->

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Promote cold-start handling for new SKUs from the production-gaps prose into an architectural primitive in the General Architecture Pattern. Specifically: the segmentation step (Step 2) detects new SKUs (count of historical observations below a threshold, e.g., 30 days), routes them to a `cold_start` segment with explicit lookup discipline (predecessor-from-master-data first, similar-SKU-from-category-clustering second, configured-default third), stamps the DynamoDB record with `cold_start_strategy` and `cold_start_until_date`, and emits a `sku_in_cold_start` CloudWatch metric per facility per segment. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Promote forecast monitoring and drift detection from the production-gaps prose into an architectural primitive. Add a separate drift-detection Lambda (or Step Functions step) invoked from EventBridge on its own cadence after each cycle's actuals are available; it joins the prior cycle's forecasts against the current cycle's consumption, computes per-SKU and per-segment forecast error, writes metrics to CloudWatch with dimensions `(facility, segment, sku_value_tier)`, and alerts on two-consecutive-cycle threshold breaches for high-value SKUs. The drift detector is distinct from the release-time quality gate in Step 3. -->

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3 and a forecasting library like Prophet or statsmodels, check out the [Python Example](chapter12.02-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

<!-- TODO (TechWriter): N3. The Python companion file (chapter12.02-python-example.md) has been drafted and reviewed; confirm cross-link target rendering at publication time. -->

### Expected Results

**Sample output for a single SKU's 90-day forecast and reorder point:**

```json
{
  "facility_id": "main-hospital-001",
  "sku_id": "GLOVE-NITRILE-MED-100CT",
  "segment": "smooth",
  "forecast_date_from": "2026-04-15",
  "forecast_horizon_days": 90,
  "mean_demand_horizon": 8460,
  "lower_bound": 7920,
  "upper_bound": 9010,
  "reorder_point": 1240,
  "order_quantity": 2400,
  "generated_at": "2026-04-14T07:00:00Z",
  "model_version": "prophet-supplies-v2-2026-04-01"
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end pipeline runtime (5,000 SKUs, single facility) | 30–90 minutes weekly |
| Forecast accuracy (smooth SKUs, 30-day MAPE) | 8–15% |
| Forecast accuracy (intermittent SKUs, 30-day MASE) | 0.85–1.10 (lower is better; below 1.0 beats naive) |
| Procedure-driven SKU accuracy | Strongly dependent on case forecast quality |
| Stockout reduction (mature deployment) | 30–60% relative to par-level baseline |
| On-hand inventory reduction | 10–25% at the same service level |
| Cost per facility per month | $100–$400 (dominated by SageMaker compute and SKU count) |

<!-- TODO (TechWriter): A1. Accuracy and operational benchmarks above are typical industry figures for healthcare supply forecasting on facilities with 2+ years of clean consumption history and a moderate SKU portfolio. Confirm these ranges against your reference data sources before publication. -->

**Where it struggles:** SKUs with fewer than 18 months of clean history (annual seasonality cannot be learned, intermittent classification is unreliable). Pandemic and emergency periods, where consumption was driven by exogenous factors that no SKU-level model can predict. Substituted or recently-renamed SKUs whose history is split across multiple identifiers without proper master-data reconciliation. Niche specialty items with single-digit annual usage (the math itself fails: there's nothing to forecast). Items affected by formulary changes, vendor swaps, or surgeon-preference changes that happened recently and aren't yet reflected in history.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. Deploying this to a real health system requires addressing several gaps that are intentionally outside the scope of a cookbook recipe.

**SKU master data quality.** Everything downstream depends on a clean SKU master with accurate categorization, lead times, vendor information, and successor-mapping for retired items. In most hospitals this data is held together with duct tape and tribal knowledge. Production systems need a maintained master data layer (often built atop the GHX or Workday item catalog) that the pipeline can rely on.

**Cold-start handling for new SKUs.** A new SKU enters the catalog with no history. Per-SKU models have nothing to fit. Production options include: (1) borrow demand from the predecessor SKU using the master data successor map; (2) borrow from a similar SKU using item-category clustering; (3) carry a configured starting reorder point until enough history accumulates (usually three months). Pick one and implement it; do not let the pipeline silently emit zeros.

**Demand regime breaks.** Pandemics, recalls, formulary changes, and contract switches all introduce regime breaks where past data is no longer representative. The pipeline needs explicit signals (a "regime break" flag in the SKU master per date range) and must either exclude those periods, downweight them, or model them with a separate intercept.

**Forecast monitoring and drift detection.** Track per-SKU forecast error against actuals on a rolling basis. Alert when error exceeds tolerance for two consecutive cycles for high-value SKUs. Retrain on a configurable cadence (monthly is reasonable for most segments) and on-demand when drift is detected. Without this monitoring, the first sign of model degradation is a clinician complaining about stockouts.

**Service level differentiation by clinical importance.** A 95% service level is fine for paper towels. It is not fine for emergency drugs. Production systems carry per-SKU service level targets that reflect clinical criticality. The reorder calculation reads each SKU's target rather than applying a single global value.

**Idempotency, audit trail, and rerun safety.** Materials management decisions feed downstream into purchase orders. The pipeline outputs need to be reproducible and auditable. Each forecast run writes to a versioned model artifact, the DynamoDB writes overwrite cleanly by primary key, and an immutable audit log captures which model version produced which reorder point.

**Integration with the ERP / materials management system.** The forecasts are useless until they actually influence reorder decisions. The integration is rarely a one-shot DynamoDB write; it's typically a flat-file extract or an API call into the ERP that runs on its own cadence and reconciles. Plan for this engineering work, which often dwarfs the modeling work in scope.

<!-- TODO (TechWriter): Expert review N2 (LOW). Specify the ERP-integration egress path options: an on-premises ERP via a Direct Connect link or VPN with the ERP-integration Lambda in the VPC; a hosted ERP via a PrivateLink endpoint where the vendor offers one; a public-internet API call only when the alternatives are not available, in which case egress traffic routes through a NAT gateway with logging and the API call uses TLS 1.2-or-higher with mutual-TLS or signed-JWT authentication. -->

---

## The Honest Take

The model selection question gets way more attention than it deserves. As with appointment forecasting, Prophet, ETS, and SARIMA are within a few percentage points of each other on the smooth SKUs that drive most of your inventory dollars. The hard work is in the segmentation logic and the master-data plumbing. Spend your time there.

The thing that surprised me the first time I built one of these: the value isn't in the forecast itself, it's in the reorder point updates. Materials managers don't sit around looking at forecasts. They live and die by par levels. If the pipeline produces beautiful forecasts but doesn't translate them into updated reorder points that flow into the ERP, you've built a research project, not an operational system. Invest disproportionately in the integration layer.

Intermittent demand is genuinely harder than the smooth case. Don't underestimate the long tail of slow-moving SKUs. They aren't where most of your inventory dollars sit, but they're where stockouts hurt the most clinically. The smooth high-volume SKUs almost forecast themselves; the intermittent specialty items are where domain knowledge plus the right method (Croston/SBA) plus segmentation routing actually earns its keep.

Concept drift is silent and constant. Surgeons change preferences. Vendors change. Contracts change. New devices enter the formulary. Without monitoring and regular retraining, a pipeline that worked beautifully for a year quietly becomes wrong over the next year. The cost of catching it in week three is two weeks of bad reorder decisions; the cost of catching it in month six is a year of stockouts and over-buys that nobody traced back to the model.

The part that's genuinely hard to communicate to operations: the prediction interval, not the point estimate, is the operational primitive. Materials managers want to ask "what's the worst plausible demand over my lead time so I don't run out?" not "what's the expected demand?" Build the user interface around the upper bound of the interval and the safety stock that backs it out, not the mean. The mean is an interesting summary statistic; the interval is what informs the order.

---

## Variations and Extensions

**Hierarchical forecasting.** When you have many related SKUs (size variants of the same glove, different presentations of the same drug), forecasts at different aggregation levels (SKU, category, vendor) tell different stories. Hierarchical forecasting reconciles all levels so that they are coherent, often producing more stable forecasts at every level. The MinT (minimum trace) reconciliation method is the modern reference for this.

**Probabilistic ordering with newsvendor logic.** For perishable or short-dated items, the order-quantity question is a newsvendor problem: the cost of over-ordering (waste, expiry) is different from the cost of under-ordering (stockout). A probabilistic forecast plus a newsvendor calculation produces a quantile-based order quantity that minimizes expected cost. This is straightforward to add once you have the probabilistic forecast and is materially better than fixed safety stock for short-shelf-life items.

**Multi-facility pooling and substitution.** Health systems with multiple facilities can pool inventory across nearby sites and meet demand surges by transfer rather than emergency order. Adding a transfer-cost-aware optimization layer on top of the per-facility forecasts captures this. It connects naturally to Recipe 14.10 (Health System Network Design).

**Linkage to scheduled cases for procedure-driven SKUs.** The procedure-driven branch of the segmentation can be substantially improved by ingesting the OR schedule directly as an input. A confirmed surgical case three weeks out is much stronger signal than the historical demand pattern. This requires a tight integration with the surgical scheduling system and a per-procedure-type usage table.

---

## Related Recipes

- **Recipe 12.1 (Appointment Volume Forecasting):** Uses the same forecasting machinery for ambulatory volume. The supply forecast for procedure-driven SKUs depends on the underlying case forecast.
- **Recipe 12.5 (Hospital Census Forecasting):** Drives demand for inpatient consumables (linens, room kits, certain medications) via the inpatient day forecast.
- **Recipe 14.3 (Inventory Reorder Optimization):** Consumes the forecast and reorder points produced by this recipe and applies a more sophisticated optimization layer (multi-echelon, newsvendor) on top.
- **Recipe 14.10 (Health System Network Design):** For multi-facility systems, the supply forecast plus the network design optimization decides where to hold inventory across the system.
- **Recipe 7.1 (Appointment No-Show Prediction):** For procedure-driven SKUs in clinic settings, the no-show-adjusted case forecast feeds into supply consumption more accurately than the booked-case forecast.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker DeepAR Forecasting Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/deepar.html)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html): Pattern for fanning out per-segment training jobs in parallel
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker examples including DeepAR notebooks for multi-series forecasting and time-series tutorials

**External Resources:**
- [Prophet Documentation (Meta Open Source)](https://facebook.github.io/prophet/): Reference for the Prophet forecasting library used in the recipe's Python companion
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook covering classical forecasting methods, including chapters on hierarchical reconciliation and intermittent demand
- [statsmodels Documentation](https://www.statsmodels.org/stable/): Python implementation of ETS, ARIMA, and other classical methods used for the smooth-segment models

**AWS Solutions and Blogs:**
- [Transitioning Amazon Forecast to SageMaker Canvas](https://aws.amazon.com/blogs/machine-learning/transition-your-amazon-forecast-usage-to-amazon-sagemaker-canvas/): Migration guidance for teams previously using Amazon Forecast

<!-- TODO (TechWriter): N4. Audit all external links during final pre-publication pass. The Forecasting: Principles and Practice link is stable; AWS blog and docs links should be re-verified. -->

---

## Estimated Implementation Time

- **Basic pipeline (single facility, smooth SKUs only):** 2–3 weeks
- **Production-ready (full segmentation, intermittent methods, monitoring, ERP integration):** 8–12 weeks
- **With variations (hierarchical, multi-facility pooling, newsvendor):** 16–20 weeks

---

## Tags

`time-series` · `forecasting` · `prophet` · `croston` · `sba` · `deepar` · `sagemaker` · `glue` · `dynamodb` · `step-functions` · `supply-chain` · `inventory` · `reorder-point` · `safety-stock` · `simple` · `mvp` · `hipaa`

---

*← [Recipe 12.1: Appointment Volume Forecasting](chapter12.01-appointment-volume-forecasting) · [Chapter 12 Index](chapter12-index) · [Next: Recipe 12.3 - ED Arrival Forecasting →](chapter12.03-ed-arrival-forecasting)*
