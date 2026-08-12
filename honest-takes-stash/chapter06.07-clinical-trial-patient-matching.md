<!-- Removed from chapter06.07-clinical-trial-patient-matching.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The structured pre-screen is the part that works reliably. Demographics, labs, medications, diagnosis codes: these are well-defined, queryable, and deterministic. If a patient's A1C is 6.2 and the trial requires > 7.5, that's a definitive exclusion. No ambiguity. You can build this part in a few weeks and it immediately saves coordinator time.

The NLP piece is where things get interesting and frustrating in equal measure. Negation detection has gotten genuinely good (Comprehend Medical handles it well for common patterns), but complex sentence structures still trip it up. "Patient reports that her mother had breast cancer but she herself has never been diagnosed with any malignancy" contains both a family history mention and a personal negation. Getting that right consistently requires either very good models or very careful prompt engineering.

The biggest surprise in production: the criteria that seem simplest are often the hardest. "On metformin monotherapy for at least 90 days" sounds straightforward until you realize that medication lists in EHRs are notoriously unreliable. Medications get added but never removed. Patients stop taking drugs without telling anyone. The "active medication list" is aspirational, not factual. You end up needing pharmacy fill data (which requires a separate integration) to have any confidence in medication duration.

The precision/recall tradeoff is real and you need to make it explicit with your research team. High precision (only surface patients who are almost certainly eligible) means coordinators waste less time but you miss eligible patients. High recall (surface anyone who might be eligible) means more coordinator work but fewer missed opportunities. Most sites start with high recall and tighten over time as they calibrate.

One more thing: the system gets dramatically more useful when you have multiple active trials. Screening for one trial is a project. Screening for 20 trials simultaneously against the same patient population is where the ROI compounds. A patient who doesn't qualify for Trial A might be perfect for Trial B. Build the system to handle multiple concurrent trials from day one.

---

