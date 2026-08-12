<!-- Removed from chapter09.03-wound-photography-measurement.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I've learned about wound measurement systems:

**The algorithm is the easy part.** Getting a U-Net to segment wounds with 0.85+ Dice score is achievable with a few thousand annotated images and standard training practices. The hard part is everything around the algorithm: getting clinicians to use the reference marker consistently, handling the infinite variety of real-world lighting conditions, integrating with EHR documentation workflows, and maintaining the system when the model's performance drifts over time.

**Clinician compliance with the capture protocol is your biggest risk.** You can build the most accurate segmentation model in the world, and it's worthless if nurses forget to include the reference marker in 40% of photos. Design for graceful degradation: if no marker is detected, still store the image and segmentation, but flag the measurement as "relative only, not calibrated." Something is better than nothing.

**Longitudinal consistency matters more than single-measurement accuracy.** A system that's consistently 5% off but reproducible is more clinically useful than one that's sometimes perfect and sometimes 20% off. Clinicians care about trends. If your system says the wound went from 5.0 cm² to 4.5 cm² to 4.1 cm², they trust the trajectory even if the absolute numbers are slightly off. Inconsistency kills trust.

**Watch for measurement drift when you retrain.** As you collect more annotated wound images and retrain your segmentation model, validate against a held-out test set AND compare measurements on a cohort of recent wounds against the previous model version. A new model that systematically measures 10% smaller would create false "healing" signals across your entire patient population. Production variant routing (serving both old and new models simultaneously on a percentage split) lets you A/B test new models before full rollout.

**Start with a single wound type.** Pressure ulcers are the best starting point: they're common, they're on relatively flat body surfaces (sacrum, heels), they have well-defined staging criteria, and there's strong clinical motivation for objective measurement (CMS quality reporting, litigation risk). Don't try to handle every wound type on day one.

**The regulatory path is lighter than you'd expect.** Wound measurement tools that only measure and document (without recommending treatment) are generally Class I or Class II medical devices under FDA guidance. The moment you add "this wound is not healing, consider X intervention," you're in a different regulatory category. Consult regulatory counsel for your specific claims and intended use.

---

