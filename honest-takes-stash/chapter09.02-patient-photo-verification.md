<!-- Removed from chapter09.02-patient-photo-verification.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Face comparison is genuinely one of the easier computer vision problems to get working. The technology is mature, the APIs are straightforward, and accuracy under good conditions is excellent. If this were a consumer app, you'd ship it in a week.

Healthcare makes it harder, but not for the reasons you'd expect. The technical accuracy is fine. What slows you down is everything around the technology: consent workflows, bias evaluation, fallback paths, regulatory compliance across multiple state laws, and organizational politics around biometric data collection.

The thing that surprised me most: the enrollment photo quality matters more than the verification photo quality. If the reference photo was taken with a low-resolution camera in bad lighting three years ago, every subsequent verification will struggle. Invest in good enrollment hardware and process. A well-lit, high-res enrollment photo makes every future verification easier.

My other hard-won lesson: never make face comparison a gate. Make it a signal. The moment your system denies someone care because a face match failed, you've created a patient safety incident, a legal liability, and probably a PR disaster. The design must always degrade gracefully to human verification. The face match should make the process faster and more secure when it works, not create a new failure mode when it doesn't.

The bias question is real and you cannot dismiss it. Test your system. Publish your results internally. Set up monitoring dashboards that track match rates by available demographic data. If you see disparities, fix them before scaling. The healthcare industry has a long history of deploying technology that works differently for different populations. Don't add to that history.

---

