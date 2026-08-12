<!-- Removed from chapter14.09-chemotherapy-scheduling.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I've learned about chemotherapy scheduling optimization that the textbooks don't tell you:

**The hardest part isn't the math. It's the data.** You can build a beautiful constraint model, but if your infusion duration estimates are off by 30%, your schedule falls apart by 10 AM. Invest heavily in duration prediction. The difference between "protocol says 4 hours" and "this patient on this regimen on cycle 6 typically takes 3 hours 20 minutes" is the difference between 65% and 82% utilization.

**Pharmacy coordination is the secret weapon.** Most scheduling systems treat pharmacy as an external dependency. The centers that get the best results model pharmacy as a first-class resource in the optimization. When the scheduler knows that pharmacy can only prep 8 bags per hour, it naturally spreads start times and eliminates the 8 AM rush.

**Staff trust takes longer than the technical build.** Nurses and schedulers have been doing this manually for years. They're good at it. They have intuitions that are hard to encode ("Mrs. Johnson always needs extra time on Tuesdays because her caregiver drops her off late"). If the system overrides their judgment without explanation, they'll route around it. Build in transparency: show why the optimizer made each decision. Allow overrides. Track when overrides improve outcomes (they often do, early on).

**Start with the batch problem, not real-time.** The overnight schedule generation is where 80% of the value lives. Real-time rescheduling is sexy but complex. Get the batch optimizer working well first. Many centers see dramatic improvement just from better initial schedules, even without real-time adjustment.

**The objective function is political.** Maximizing utilization might mean scheduling patients at inconvenient times. Maximizing patient preference might mean lower utilization. Leveling nursing workload might mean some patients wait longer. These tradeoffs are not technical decisions. They're organizational values. Get leadership to explicitly weight the objectives before you build.

**Simulation is your best friend for validation.** Before deploying an optimizer, run it against 6 months of historical schedules. Compare its output to what actually happened. Where does it do better? Where does it do worse? This builds confidence and reveals blind spots in your constraint model.

---

