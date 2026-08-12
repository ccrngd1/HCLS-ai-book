<!-- Removed from chapter15.07-chronic-disease-treatment-personalization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what becomes clear once you actually try to build this: the RL algorithm is maybe 10% of the work. The other 90% is data engineering, clinical validation, and trust-building.

The data pipeline is brutal. EHR medication records are a mess. Patients switch providers, change insurance, fill prescriptions at different pharmacies. Mapping free-text prescriptions to standardized treatment levels requires medication reconciliation logic that handles brand names, generics, combination pills, and dose ranges. Adherence estimation from pharmacy claims (proportion of days covered) is a rough proxy at best. And temporal alignment of irregularly-spaced visits into consistent quarterly decision points requires judgment calls about what counts as "close enough to 3 months."

The reward function is where clinical and ML expertise must collaborate intensely. I've seen teams optimize HbA1c aggressively, only to realize their policy was recommending insulin for patients who would have done fine on oral medications with better adherence support. The "adherence mismatch" penalty in the reward function exists because of this exact failure mode. Always decompose your reward into components and track each one separately. A single aggregate number hides dangerous trade-offs.

The safety constraint layer often matters more than the RL policy itself. A simple "follow ADA guidelines" algorithm with good safety constraints can outperform a sophisticated RL policy with weak constraints. The constraints encode decades of clinical trial evidence. The RL policy adds value at the margins: better personalization for patients who don't fit neatly into guideline categories, better anticipation of trends, better handling of competing comorbidities. But the constraints keep patients safe.

The biggest surprise: clinician agreement rate is actually a feature, not a bug. When your BCQ policy agrees with clinicians 75% of the time, that's good. It means the policy learned that clinicians are mostly right. The interesting 25% is where the policy disagrees, and those disagreements need careful case-by-case review before you trust them. Some will be genuine improvements (the policy noticed a trend the clinician missed). Some will be artifacts of limited training data. You can't tell which is which without clinical review.

Plan for 3-5 years from "working prototype" to "influencing treatment decisions in one clinic." That's not pessimism; that's the reality of clinical AI deployment for treatment recommendations.

---

