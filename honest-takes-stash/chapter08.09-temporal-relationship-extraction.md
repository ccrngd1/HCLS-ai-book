<!-- Removed from chapter08.09-temporal-relationship-extraction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Temporal relationship extraction is one of those problems where the research papers report 0.75 F1 and you think "that's not great but it's something." Then you deploy it and realize that 0.75 F1 on curated benchmark data translates to maybe 0.60 on your institution's actual clinical notes, because your neurologists write differently than the training corpus, your EHR templates create weird formatting artifacts, and half your notes have batch-charted timestamps that don't match the event times.

The thing that surprised me most: the temporal expression recognition part is basically solved. HeidelTime and similar tools handle 90%+ of temporal expressions correctly. The hard part, the thing that makes this a "complex" recipe, is the relationship classification between events. Specifically, the implicit temporal relationships where there's no explicit signal word and the ordering relies on clinical reasoning ("antibiotics started, then cultures resulted" implies BEFORE because that's how clinical practice works, not because the text says "before").

If I were starting over, I'd spend less time on the relation classifier and more time on the candidate pair generation. The truth is that most temporal relationships in a clinical note follow one of a few patterns: events listed in narrative order are chronological, events in the same sentence with a temporal connective have that relationship, and events anchored to the same temporal expression overlap. A rule-based system covering just those patterns gets you 70% of the way there. The ML classifier handles the remaining 30% of ambiguous cases, and honestly gets a meaningful fraction of those wrong.

The other thing: cross-document temporal reasoning (stitching together timelines from multiple notes over months or years) is the real clinical value. But it's 10x harder than single-document extraction because you need coreference resolution (is "the knee pain" in today's note the same episode as "left knee arthralgia" from six months ago?) and you need to handle contradictions between documents. Most production systems skip cross-document and just do single-document timelines. Reasonable, but it means the longitudinal patient story remains fragmented.

My honest recommendation: if your use case is building a visual timeline for clinician review (where a human verifies and corrects), temporal extraction at 0.70-0.75 accuracy is genuinely useful. It gets the ordering roughly right and the clinician fixes the errors in seconds. If your use case is feeding temporal relationships into an automated system (pharmacovigilance causality assessment, clinical trial eligibility screening), you need higher accuracy than the current state of the art provides, and you should plan for a human-in-the-loop.

---

