<!-- Removed from chapter07.07-length-of-stay-prediction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you when you build this:

The model's biggest errors are almost never clinical. They're social. The patient who is medically ready on day 4 but waits until day 9 because there's no SNF bed, or because the family can't arrange home oxygen, or because the patient is homeless and there's nowhere safe to discharge them. Your model will learn that Medicaid patients stay longer (because they do, on average), but it won't understand why. And that "why" is where the intervention opportunity lives.

The DRG geometric mean LOS is both your best feature and your biggest trap. It's the single strongest predictor of actual LOS (because DRGs are designed to group clinically similar patients). But it also encodes historical patterns that may not reflect your hospital's current processes. If your hospital is systematically faster or slower than the national average for a given DRG, the model needs to learn that local calibration.

Clinician trust is the adoption bottleneck, not model accuracy. A model that's right 75% of the time but wrong in ways that feel random to clinicians will be ignored. A model that's right 70% of the time but explains its reasoning (top contributing features) and acknowledges uncertainty (confidence intervals) will be used. Invest in explainability.

The daily update is where the real value lives. An admission-time prediction is a starting point. The prediction that updates on day 2 when the patient spikes a fever and gets started on IV antibiotics, that's what changes operational decisions. Build the real-time pipeline from day one, not as a phase 2.

Retraining cadence matters more than you'd think. Hospital operations change seasonally (flu season, summer trauma), with new initiatives (discharge by noon programs), and with staffing changes. A model trained on 2024 data may be poorly calibrated for 2026 operations. Monthly retraining with a 12-month rolling window is a reasonable starting point.

---

