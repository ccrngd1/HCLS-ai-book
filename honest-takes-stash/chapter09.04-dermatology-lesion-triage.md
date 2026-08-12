<!-- Removed from chapter09.04-dermatology-lesion-triage.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you when you actually build this:

**The model is the easy part.** Fine-tuning an EfficientNet on ISIC data to get 90% accuracy on a held-out test set takes a weekend. Getting clinicians to trust it, patients to use it correctly, and the organization to accept liability for it takes months to years.

**Photo quality is your real enemy.** In a research paper, every image is a perfectly lit, centered dermoscopic capture. In production, you'll get bathroom selfies with a phone flash creating a white hotspot directly on the lesion. Your quality gate will reject 15-25% of submissions, and users will be frustrated. Invest heavily in the capture UX: guides, overlays, real-time feedback on positioning and lighting.

**The skin tone bias is not something you can fix with a disclaimer.** If your model performs 15% worse on dark skin, deploying it with a footnote saying "results may vary" is not acceptable. Either acquire diverse training data and validate rigorously, or restrict deployment to populations where you've demonstrated adequate performance. This is an equity issue with real clinical consequences.

**Threshold tuning is a political process, not a technical one.** The dermatology department wants low false-positive rates (they're already overwhelmed). Patient safety advocates want high sensitivity (never miss a melanoma). Administration wants to demonstrate AI value. You'll spend more time in meetings about thresholds than you will training the model.

**Outcome tracking is essential but hard.** To know if your model is actually working, you need to close the loop: what did the dermatologist actually diagnose? Was the triage category correct? This requires integration with the dermatology workflow and a process for recording outcomes back to the triage record. Without it, you're flying blind.

**Regulatory is not optional.** Even for "triage only," the FDA's guidance on Clinical Decision Support software applies. If your system's output is intended to be acted upon without independent clinician review, it's likely a medical device. If a dermatologist always reviews every case regardless of the AI output, you have more flexibility. Document your intended use carefully and get regulatory counsel involved early.

---

