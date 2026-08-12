<!-- Removed from chapter12.03-ed-arrival-forecasting.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The model selection question gets far more attention than it deserves. For most ED arrival forecasting problems, a Poisson regression with thoughtful features lands within a few percentage points of Prophet, which lands within a few percentage points of DeepAR. The hard work is in the data quality (clean ADT history, accurate ESI labels, integrated weather feed, maintained event calendar), not in the choice of forecasting algorithm. Spend your time on the data plumbing.

The thing that surprised me the first time I built one of these: the forecast that the charge nurse actually wants is not the volume forecast. It's the answer to "do I need to call someone in?" That question is a function of forecast volume, current census, current acuity mix, current boarder count, current staff level, and the operational definition of "overwhelmed." The forecast is one input. The decision is the integration of all of them. Build the dashboard around the decision, not around the model output.

Acuity is harder than volume. Volume forecasts converge nicely with a few years of history and the right features. Acuity mix is more sensitive to short-term shifts (a flu wave concentrates ESI 3 visits, a heat wave concentrates ESI 2 visits) and the historical training data may not match the immediate present. Building a separate, faster-retraining acuity model that updates more frequently than the volume model is a worthwhile refinement once the basic pipeline is stable.

Concept drift is real and faster than you think. ED catchment areas change as competitors open or close. Local population shifts as housing develops or contracts. Telehealth and urgent care eat into low-acuity walk-in volume; that boundary moves year over year. A model trained on 2023 data and deployed in 2026 will be wrong about the 2026 mix in ways you can't fully predict. Bake monitoring in from day one. The cost of catching drift in week three is two weeks of stale forecasts; the cost of catching it in month six is six months of unexplained operational underperformance.

The part that's genuinely hard to communicate to operations: the prediction interval, not the point estimate, is the operational primitive. ED leaders want to know "what's the worst plausible four-hour window in the next twenty-four hours so I can pre-position staff?" not "what's the expected count for the 18:00 hour?" Build the dashboard around the upper bound of the interval and the surge plan trigger that backs out of it. The mean is interesting; the upper tail is what informs the call-in decision.

---

