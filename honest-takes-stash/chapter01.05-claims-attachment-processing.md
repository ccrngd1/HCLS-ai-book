<!-- Removed from chapter01.05-claims-attachment-processing.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The rule-based boundary detection in the original published version of this recipe was more code than it looked. You had the signal extraction for each type (header text parsing, page restart regex, date extraction, fuzzy comparison logic), the signal priority ordering, the tuned thresholds for each signal, and the override rules for when multiple signals fired at once. It worked. On the documents it was calibrated to, it worked well.

Then a provider started sending packages where their EHR printed a running date header on every page, including when the document type changed. Date discontinuity: no signal. Header continuity: strong "same document" signal. The boundary detection missed every transition in that provider's submissions. The fix was another special case in the header comparison logic. And then another provider did something different. The rule list grew.

The LLM approach doesn't eliminate errors. The model still misses boundaries occasionally, particularly on the continuous EHR print job problem I mentioned above. But the failure modes are different. The rule-based system failed systematically on predictable template variations. The LLM fails on genuinely hard cases: pages that really are ambiguous, documents that don't have any of the standard signals, content that would confuse a human reviewer too. That's a better failure distribution.

The claim line matching improvement is the one that genuinely surprised me. I went in expecting the LLM to do marginally better than the lookup table, catching some edge cases that the dictionary missed. What I actually got was a model that could explain its reasoning: "The procedure description says 'right total knee arthroplasty with cemented components,' which is consistent with CPT 27447. The date of service in the document (March 15) matches the claim line." The explanation is what the examiner needs when they're reviewing a claim. Not just a match/no-match flag, but the evidence behind it.

Here's the cost reality, because I promised honesty. The Textract cost hasn't changed: it still dominates the per-package bill at around $2.00 for a 30-page package. The LLM costs are smaller than you might expect. Nova Lite boundary detection on 29 page pairs costs less than a cent. Nova Lite classification on 5 documents costs less than a cent. The Claude Sonnet 4.6 claim matching calls (one per clinical document, 3 to 4 calls per package) run about $0.05 to $0.12 per package. The total per-package cost is actually somewhat lower than a comparable Comprehend Medical per-character billing pipeline, while producing richer output. The math on this one works out in your favor.

The one cost trap to avoid: don't run the full segment text through Claude Sonnet 4.6 for every step. The clinical extraction prompt already summarizes the document; the claim matching step uses that summary, not the raw page text. Keeping the claim matching inputs tight (structured extraction outputs rather than raw document text) is what keeps the per-claim Sonnet spend reasonable.

The path from this recipe to production runs through measurement, feedback loops, and model version management. None of that is glamorous. All of it matters.

---

