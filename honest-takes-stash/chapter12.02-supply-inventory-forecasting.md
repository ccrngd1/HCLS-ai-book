<!-- Removed from chapter12.02-supply-inventory-forecasting.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The model selection question gets far more attention than it deserves. As with appointment forecasting, Prophet, ETS, and SARIMA are within a few percentage points of each other on the smooth SKUs that drive most of your inventory dollars. The hard work is in the segmentation logic and the master-data plumbing. Spend your time there.

The thing that surprised me the first time I built one of these: the value isn't in the forecast itself, it's in the reorder point updates. Materials managers don't sit around looking at forecasts. They live and die by par levels. If the pipeline produces beautiful forecasts but doesn't translate them into updated reorder points that flow into the ERP, you've built a research project, not an operational system. Invest disproportionately in the integration layer.

Intermittent demand is genuinely harder than the smooth case. Don't underestimate the long tail of slow-moving SKUs. They aren't where most of your inventory dollars sit, but they're where stockouts hurt the most clinically. The smooth high-volume SKUs almost forecast themselves; the intermittent specialty items are where domain knowledge plus the right method (Croston/SBA) plus segmentation routing actually earns its keep.

Concept drift is silent and constant. Surgeons change preferences. Vendors change. Contracts change. New devices enter the formulary. Without monitoring and regular retraining, a pipeline that worked beautifully for a year quietly becomes wrong over the next year. The cost of catching it in week three is two weeks of bad reorder decisions; the cost of catching it in month six is a year of stockouts and over-buys that nobody traced back to the model.

The part that's genuinely hard to communicate to operations: the prediction interval, not the point estimate, is the operational primitive. Materials managers want to ask "what's the worst plausible demand over my lead time so I don't run out?" not "what's the expected demand?" Build the user interface around the upper bound of the interval and the safety stock that backs it out, not the mean. The mean is an interesting summary statistic; the interval is what informs the order.

---

