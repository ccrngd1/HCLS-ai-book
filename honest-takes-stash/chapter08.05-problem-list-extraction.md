<!-- Removed from chapter08.05-problem-list-extraction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Problem list extraction is one of those problems that feels like it should be 90% solved by off-the-shelf NER, and in some sense it is. The extraction piece works well. You'll get most problem mentions out of a note with reasonable accuracy on your first attempt.

The hard part is everything after extraction. Assertion classification is where the pain lives. Getting negation right 95% of the time sounds great until you realize that 5% error rate on a 3000-patient panel means dozens of patients with incorrectly flagged conditions. And the failure mode is asymmetric: a false positive (adding a negated condition to the active list) erodes clinician trust in the system much faster than a false negative (missing a real problem) does.

The reconciliation logic is where the real engineering challenge hides. SNOMED concept hierarchies are complex, and determining whether two codes represent "the same problem at different specificity levels" versus "genuinely different conditions" requires clinical ontology reasoning that's harder than it looks. "Type 2 diabetes" and "Type 2 diabetes with diabetic nephropathy" are in the same hierarchy, but one is a specificity upgrade of the other. "Type 2 diabetes" and "diabetic foot ulcer" are related but are genuinely separate problem list entries.

What surprised me most: the section detection step (which seems like simple string matching) has an outsized impact on overall accuracy. Notes without clear section headers, or with non-standard formatting, degrade assertion classification significantly. The NER engine extracts the condition fine; it's the "does this patient actually have it" determination that suffers when section context is missing.

One more thing. Problem list extraction is inherently a clinician-in-the-loop workflow. You're generating recommendations, not making changes. The moment you auto-add conditions to a problem list without physician review, you've crossed from decision support into autonomous clinical documentation. That's a different regulatory and liability landscape entirely. Keep the human in the loop. Frame your pipeline as "here are problems you might want to add" not "I've updated the problem list for you."

---

