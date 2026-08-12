<!-- Removed from chapter08.02-patient-sentiment-analysis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Sentiment analysis is one of those problems where the demo looks amazing and production looks humbling. You'll get the system running in a week, watch it correctly classify 85% of feedback, and feel great. Then you'll look at the 15% it gets wrong and realize those are disproportionately the comments you cared about most.

The hardest cases are the most important cases. A patient who writes a polite, measured paragraph about how they're never coming back (no explicit negative words, no profanity, just quiet disappointment) will probably be classified as neutral. A patient who writes "WORST EXPERIENCE EVER!!!!" is easy for the machine but usually less operationally interesting. The signal-to-noise tradeoff is real.

Aspect extraction requires real investment in labeled data. You need at minimum a few hundred labeled examples per aspect category, reviewed by people who understand both NLP and your patient experience goals. Plan for a 2-4 week labeling sprint before your custom classifier is useful. And plan to refresh that data every 6-12 months as language patterns evolve.

The thing that surprised me most: the aggregate trends are far more valuable than individual predictions. Any single feedback item might be misclassified. But when you aggregate 5,000 items and see that `wait_time` sentiment dropped 20% in the last month for your orthopedics department, that's real signal that survives individual classification errors. Design your system for aggregate intelligence, not individual-comment accuracy.

One more thing: be careful about who sees the raw comments. Patient experience teams need access. But department leaders who see their own negative feedback without context ("why did this patient say I was dismissive?") can react defensively rather than constructively. Present aggregated themes and trends to leadership. Keep individual comment access to the patient experience professionals who are trained to handle it.

---

