<!-- Removed from chapter14.03-inventory-reorder-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The math here is well-understood. Inventory optimization has been a solved problem in manufacturing and retail for decades. The hard part in healthcare isn't the solver; it's the data.

Your ERP's inventory levels are probably wrong. Not dramatically wrong, but off by enough to matter. Supplies get consumed without being scanned. Items move between departments informally. Par levels get adjusted manually without updating the system. The optimization model will faithfully produce optimal policies for the inventory levels it sees, which may not match reality. Garbage in, garbage out, but with a veneer of mathematical rigor that makes it harder to spot.

The criticality classification is where politics enters. Everyone thinks their department's supplies are "critical." You need clinical leadership to define and enforce the tiers, because the optimizer will allocate more budget and space to critical items at the expense of standard ones. That's a resource allocation decision disguised as a technical parameter.

Expiration management is the sleeper complexity. The model above handles it as a constraint (don't order more than you can use before expiry), but real expiration management requires FIFO tracking, rotation policies, and redistribution logic for items approaching their date. That's a separate operational system that the optimizer needs to integrate with, not replace.

The thing that surprised me most: the biggest savings often come not from optimizing individual item policies, but from consolidating orders across items to hit volume discount breakpoints. A model that optimizes items independently misses these cross-item synergies. Adding order consolidation logic (grouping items by distributor, timing orders to hit price breaks) can double the cost savings, but it also doubles the model complexity.

Start with the basic model. Get the data pipeline right. Prove value on a subset of items. Then add sophistication.

---

