<!-- Removed from chapter09.01-image-quality-assessment.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of those problems where the technology is genuinely ready but the deployment is harder than the ML. The model itself is straightforward: binary classification on images with clear labels (your PACS already tracks rejections). Training takes a few days. Inference is fast. The accuracy is good enough.

The hard parts are all operational:

**Getting the training data out of your PACS.** Radiology departments track rejections, but the data is often in a proprietary system with no clean export path. You'll spend more time on data extraction than on model training. Budget for it.

**Calibrating thresholds per site.** What I said earlier about site-specific calibration is not optional. I've seen systems that worked beautifully at one hospital and rejected 40% of images at another because the equipment was older and the baseline noise floor was higher. Plan for a calibration phase at every deployment site.

**Technologist trust.** If the system rejects images that the technologist thinks are fine, they'll stop trusting it within a week. Start with a "shadow mode" where the system assesses images but doesn't alert anyone. Compare its decisions against actual radiologist rejections for a month. Only go live when the agreement rate is high enough that technologists see it as helpful, not annoying.

**The feedback loop problem.** Once you deploy the system and technologists start retaking flagged images, your rejection rate drops. Great. But now your model's training data (historical rejections) no longer represents the current distribution of quality problems. The model needs periodic retraining on the new failure modes that slip through.

The part that surprised me: the biggest ROI is not in radiology. It's in clinical photography. Wound care photos, dermatology images, dental radiographs. These are taken by non-imaging-specialists (nurses, medical assistants) with consumer-grade cameras, and the quality variance is enormous. A simple blur-and-exposure check on clinical photos catches more actionable problems than a sophisticated model on radiologist-acquired X-rays.

---

