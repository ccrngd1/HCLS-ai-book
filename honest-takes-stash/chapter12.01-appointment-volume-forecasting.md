<!-- Removed from chapter12.01-appointment-volume-forecasting.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The model selection question gets far more attention than it deserves. For most appointment forecasting problems, Prophet, ETS, and ARIMA are within a few percentage points of each other on accuracy. The hard work is in the data preparation and the operational integration, not in the choice of forecasting algorithm. Spend your time there.

The thing that surprised me the first time I built one of these: the prediction intervals are more useful than the point forecasts. Operations leaders want to know "what's the worst plausible Monday in the next month so I can staff for it?" not "what's the expected count for next Monday?" Build the user interface around the intervals, not the point estimate.

Concept drift is the silent killer. A pipeline that worked beautifully for a year will quietly become wrong over the next year as panels shift, providers leave, and patient mix evolves. Bake the monitoring in from day one. The cost of catching drift in week three is two weeks of bad staffing decisions; the cost of catching it in month six is a year of erosion in operational metrics that nobody traces back to the forecast.

The part that's genuinely hard: explaining to a CFO why the forecast missed badly during a specific week. The honest answer is usually "it's a statistical model, it has variance, this week landed in the tail." That answer is true and unsatisfying. Pair every forecast with its prediction interval and its historical accuracy band, so the conversation can be about whether this week was within expected error rather than whether the model is broken.

---

