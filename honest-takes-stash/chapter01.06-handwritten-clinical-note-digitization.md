<!-- Removed from chapter01.06-handwritten-clinical-note-digitization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Let me be direct about what changed and what didn't.

**What changed.** The primary extraction path is now a vision model that reads the handwriting in context, not an OCR engine producing a character string. For the genuinely difficult cases (ambiguous letterforms, context-dependent abbreviations, words that only make sense in the sentence around them) this is a meaningfully better approach. The fraction of entities routed to human review goes down. The correction rate among reviewed entities goes down. The feedback loop is a prompt library instead of a training data pipeline, which is operationally simpler.

**What didn't change.** The confidence tiering and human review requirement. Those are features of the problem, not the pipeline. Clinical notes contain PHI and drive care decisions. The stakes require that you know which extractions to trust. The three-tier structure and A2I review workflow are still the right architecture regardless of what's doing the extraction.

**The hallucination caveat is real.** Vision models fail differently from OCR models. OCR returns low confidence when it can't read a word. Vision models sometimes generate plausible-sounding text that isn't actually on the page. "Confident and wrong" is harder to catch than "low confidence." The composite score approach (combining Textract OCR confidence with vision model confidence) is specifically designed to catch the case where the image was hard to read but the vision model reported high confidence anyway. But it's not a perfect guard. Audit your false-acceptance rate actively in the first few months of production.

**The cost story is better than you might expect.** The "vision models are expensive" framing is true relative to text-only models, but the comparison that matters is the full pipeline cost. Vision extraction plus the Textract quality signal costs roughly $0.055-0.065 per page in AI inference. The original Textract-plus-Comprehend Medical approach cost $0.15 per page. The AI inference cost is lower. The downstream benefit is fewer human reviews, which is where the real money is. A page that auto-accepts at high confidence saves the full A2I review cost ($1.25 at typical reviewer rates). Routing 15-25% of entities to review instead of 25-40% adds up quickly.

**The prompt library requires attention.** The few-shot examples that improve the model's accuracy over time don't curate themselves. Someone needs to review the correction candidates periodically (monthly is reasonable), de-identify the source images, select the most instructive examples, format them as few-shot demonstrations, and update the production prompt. This is not technically complex, but it is an ongoing operational responsibility. If nobody owns it, the prompt library stagnates and the improvement feedback loop closes. Assign it explicitly before you go live.

**Provider variability is still the biggest operational challenge.** Some physicians write clearly; their notes come through at 82% average Textract confidence and the vision model handles them cleanly with under 15% entity review rates. Other physicians produce notes where 40% of entities need human review regardless of how good the AI is. The routing thresholds let you calibrate per-provider, and after a few months of production data you'll know exactly who your challenge cases are. The solution isn't better AI: it's recognizing that some handwriting genuinely requires a human, and building a workflow that gets that human involved efficiently.

---

