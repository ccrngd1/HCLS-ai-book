<!-- Removed from chapter06.09-social-determinant-phenotyping.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you when you build this:

The biggest cluster is always "we don't know." In every health system I've seen attempt SDOH phenotyping, the largest group (often 40-60% of patients) has insufficient data to assign a meaningful phenotype. They weren't screened, their notes don't mention social factors, and community-level indicators are too coarse to differentiate. Your first instinct will be to treat this as a failure. It's not. It's an honest signal that your organization needs to improve SDOH documentation and screening rates before the clustering can be maximally useful.

NLP extraction quality varies wildly by note type. Social work assessments are gold mines. Physician progress notes occasionally mention social factors in passing. Nursing intake forms sometimes capture transportation and housing. Specialist notes almost never mention SDOH. If you're only processing one note type, you're missing signal.

The equity audit is not optional. I've seen SDOH phenotyping projects produce clusters that are effectively racial categories with extra steps. If your "multi-domain social complexity" cluster is 85% patients of color, you need to ask hard questions about whether you're measuring social determinants or measuring structural racism. Both are real, but the interventions are different, and the risk of misuse is high.

Staleness is a real operational problem. Social circumstances change. A phenotype assigned 18 months ago based on a note from a crisis period may not reflect a patient's current situation. Build re-evaluation triggers: new screening data, new social work notes, address changes, or simple time-based expiration. A common cadence pattern: weekly incremental assignment (assign new patients to existing centroids) with monthly full re-clustering and equity audit. The cadence should be driven by rate of new SDOH data accumulation, not calendar alone. If your health system processes 500 new social work notes per day, weekly re-clustering makes sense. If you get a trickle of 20 notes per week, monthly is fine.

The intervention matching is where the value lives, and it's where most projects stall. Phenotyping without a clear "so what" is an academic exercise. Before you build the clustering, make sure you have community resources to connect patients to. A phenotype of "food insecurity" is only useful if you have a food assistance referral pathway ready.

---

