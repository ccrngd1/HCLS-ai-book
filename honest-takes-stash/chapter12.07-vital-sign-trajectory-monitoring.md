<!-- Removed from chapter12.07-vital-sign-trajectory-monitoring.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I wish someone had told me before building a system like this:

Alert fatigue will kill your project faster than any technical limitation. You can build the most sophisticated trajectory analysis engine in the world, and if it generates more than 2-3 meaningful alerts per nurse per shift, clinical staff will start ignoring it. I've seen beautifully engineered systems get turned off within three months because the false positive rate was too high. Design for specificity first, sensitivity second. A missed alert is bad. An ignored alerting system is worse because then you miss everything.

The medication integration is not optional, and it's not simple. Half of the "deterioration trajectories" your system detects will actually be expected pharmacological responses. A patient gets Metoprolol, and their HR drops. A patient gets Lasix, and their BP dips. Without the MAR integration, your system will cry wolf constantly. But getting real-time medication data flowing into your pipeline requires an HL7 interface to the pharmacy/EHR system, which is a 3-6 month integration project on its own.

The "general floor" use case is paradoxically harder than ICU. In the ICU, you have continuous monitoring, so your trajectories have hundreds of data points per hour. On a general medical floor, you might get vital signs every 4-8 hours. Computing a meaningful slope from 3-4 data points is statistically fragile. The confidence intervals are wide. You need fundamentally different algorithms (or you need to increase monitoring frequency for patients whose early readings are concerning, which is actually a great clinical workflow).

Patient-specific baselines are essential but create a cold-start problem. A patient admitted at 2am gets their first set of vitals. By 6am, you might have 2-3 sets. Is that enough to compute a baseline? Probably not. You can pre-seed with population norms stratified by age, sex, and admission diagnosis, but those are approximations. Some teams solve this by importing the patient's most recent outpatient vitals from the EHR to establish a pre-admission baseline. That helps a lot when the data is available.

The biggest surprise: simple works. A basic slope + deviation model with good suppression logic outperforms complex deep learning models for this use case in most deployments. The reason is interpretability. When a nurse gets an alert that says "HR slope 3.2 bpm/hr, deviation 2.4 sigma from baseline, co-occurring with RR rise," they understand it and can act on it. When a deep learning model says "deterioration probability 0.73," they don't know what to do with it. Clinical trust comes from transparency.

---

