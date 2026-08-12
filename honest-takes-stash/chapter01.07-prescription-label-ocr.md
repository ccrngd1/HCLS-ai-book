<!-- Removed from chapter01.07-prescription-label-ocr.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This one is in the "sounds easy, has real edge cases" category. The first 80% of labels you test will process beautifully. Then you'll hit a compounding pharmacy label, or a bottle photographed by a member who tilted their phone 30 degrees, or a label where the NDC field was reprinted over the original and the text overlaps.

The curved label problem is the one that catches most teams off-guard. It's not catastrophic: modern OCR handles moderate curvature surprisingly well. But "surprisingly well" is not the same as "correctly." The characters at the far edges of a wrapped label can have 10-15% higher error rates than the center of the label, and the fields most likely to live at the edges are the ones with the most characters: the drug name and the directions. Budget for it.

The SIG codebook is the part that requires the most ongoing maintenance. Latin pharmacy abbreviations are standardized in principle and inconsistent in practice. Individual pharmacies and pharmacy software systems add their own shorthand. "Inject 0.5 mL SubQ QW" and "Inject 0.5 mL SC every week" are the same instruction from different systems. Build the unrecognized-token logging on day one: you'll need it.

The RxNorm confidence cutoff is a tradeoff to calibrate for your use case. A 70% threshold is a reasonable starting point, not a gospel number. For medication reconciliation in a clinical program, you might want 85%+: a wrong RxNorm mapping in a drug interaction checker produces a false safety signal that a clinician has to investigate. For a member-facing informational display, 70% might be fine. Know your downstream use case before you pick the threshold.

The thing I didn't anticipate building the first version of this: days supply is sometimes absent from the label. State regulations on what must appear on a prescription label vary, and some states don't require days supply to be printed. Your refill metrics logic needs to handle missing fields gracefully rather than throwing an exception when the field isn't found.

---

