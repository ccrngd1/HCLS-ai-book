<!-- Removed from chapter14.07-or-case-sequencing.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The optimization itself is the easy part. Getting a solver to produce a good schedule from well-formulated constraints is a solved problem in operations research. The hard parts are everything around it.

**Duration prediction is where you live or die.** If your predicted durations are systematically wrong (and they will be, initially), the optimized schedule is fiction. Invest heavily in duration modeling before you invest in fancy solver techniques. A simple heuristic scheduler with accurate durations will outperform an optimal solver with bad duration estimates every time.

**Surgeon buy-in is non-negotiable.** Surgeons who feel the system is dictating their schedule will simply ignore it. The successful implementations I've seen treat surgeon preferences as near-hard constraints initially, then gradually demonstrate value by showing "your cases finished 30 minutes earlier because we sequenced them better." Start by optimizing within their preferences, not against them.

**The replan frequency tradeoff is real.** Replan too often and the schedule feels unstable (staff hate constant changes). Replan too rarely and you're running a suboptimal schedule all afternoon because of a morning disruption. Most teams settle on replanning only when deviation exceeds 15-20 minutes or when a cancellation/add-on occurs.

**Turnover time is where the real gains hide.** Most people focus on case duration optimization, but the 25-45 minutes between cases is where utilization is actually lost. Sequencing similar cases back-to-back (same equipment, same setup) can shave 5-10 minutes per turnover. Over a 6-case room day, that's 30-60 minutes of recovered time.

**Failure handling matters more than optimality.** When the solver fails (and it will: infeasible constraints, OOM on large instances, network timeouts), the system must fall back gracefully to the previous valid schedule and alert the perioperative coordinator. A dead-letter mechanism on the replan queue with automated alerting ensures that silent failures don't leave the OR running on a stale schedule all day.

The thing that surprised me most: the constraint that causes the most infeasibility isn't equipment or rooms. It's anesthesia coverage. When one anesthesiologist covers multiple rooms, their availability window becomes the binding constraint on the entire schedule. Model this carefully.

---

