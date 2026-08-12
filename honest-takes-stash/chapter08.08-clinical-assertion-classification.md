<!-- Removed from chapter08.08-clinical-assertion-classification.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Assertion classification is one of those problems that feels solved until you deploy it on real clinical text at scale. The benchmarks look great on clean academic datasets. Then you encounter the emergency department physician who documents in stream-of-consciousness fragments without punctuation, the copy-forward note that contains three years of historical assessments mixed with today's findings, and the templated note where half the "findings" are default text that was never edited.

The rule-based layer (NegEx-style) is genuinely underrated. It handles 60% of cases correctly and instantly. Do not skip it in pursuit of an all-ML solution. The ML model should handle the hard 40%, not the easy 60%.

The assertion taxonomy decision matters more than you'd expect. If your downstream consumers only need present/absent/family, don't build a 7-class system. More classes means more annotation cost, lower inter-annotator agreement, and harder model training. Start with fewer classes and expand only when a downstream system actually needs the granularity.

The part that surprised me: conflict resolution is where the most clinical judgment lives. When a concept is mentioned as "historical" in PMH and "present" in the Assessment, a human knows the clinician is saying "this previously resolved condition has recurred." Getting a rules-based system to make that inference reliably requires clinical knowledge that is hard to encode. In practice, most production systems sidestep conflict resolution and return all mentions with their individual assertions, letting the downstream consumer decide.

One more thing: Comprehend Medical's built-in negation detection is better than most people give it credit for. If your use case only needs present vs. absent (which covers a surprising number of use cases: quality measures, problem list maintenance, cohort identification), test Comprehend Medical's native traits before building a custom model. You might not need the custom layer at all.

---

