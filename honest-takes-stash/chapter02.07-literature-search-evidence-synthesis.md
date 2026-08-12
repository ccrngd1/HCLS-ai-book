<!-- Removed from chapter02.07-literature-search-evidence-synthesis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

I've watched more literature-search RAG projects flame out than any other category of clinical AI work. The failure patterns are consistent.

The first pattern is the demo-to-production gap. Somebody on the team builds a prototype that answers five cherry-picked questions beautifully. Leadership sees the demo. Budget gets approved. A real rollout exposes the prototype to the messy, specialty-diverse, terminologically-varied, occasionally-ambiguous questions clinicians actually ask, and the quality craters. The team spends six months chasing individual failure modes and emerges with a system that's 20-30% better than the demo but still produces too many wrong-enough answers to earn clinician trust. By month nine, the tool has a bad reputation that's very hard to recover from. The mitigation isn't more engineering; it's resisting the pressure to demo too early. Build a question-set that reflects the breadth of real queries, evaluate against that set weekly, don't show leadership the tool until it performs reasonably on the breadth set. Yes, this is politically hard. Do it anyway.

The second pattern is the corpus-quality blind spot. Teams pour effort into retrieval algorithms and embedder choice and re-ranker fine-tuning, and neglect the corpus. A world-class retrieval stack over a mediocre corpus produces mediocre answers. Auditing the corpus is boring work (checking coverage, finding stale sources, investigating why certain questions get no retrieval, verifying that guidelines are actually in the index and not just mentioned). It's also the highest-leverage work. Spend the time.

The third pattern is underestimating the validation step. "We'll have the model cite its sources" is not validation; it's formatting. Real validation (citations exist, claims match sources, numerics preserve, populations align) is a pipeline unto itself, and it's the thing that turns "looks like an answer" into "is an answer." Teams that skip this step or implement it superficially ship systems that fail the first time a motivated clinician tries to trace a claim back to its source and finds the claim isn't actually in the paper. Once that trust is gone, getting it back is brutal.

The fourth pattern is specialty-specific failure modes. A system that works well for primary-care questions can completely fall apart on oncology questions, because oncology literature has structural features (trial-heavy, abbreviation-heavy, rapid update cycle, complex subgroup analyses) that retrieval and generation handle differently. Pick a beachhead specialty, get it right, then expand. "Works for everyone" at launch usually means "works for no one."

The fifth pattern is neglecting the UX. Clinicians don't just need a good answer; they need an answer delivered in a form they can use in the thirty seconds they have. If the UI presents a wall of text without clear claim-to-citation linking, without evidence-grade framing, without the ability to click into a source paper, the tool gets closed and not reopened. UX is not a decoration on top of the ML; it's part of the product. Budget accordingly.

A few things that have worked, in my experience:

**Start with safety-interaction questions.** They're bounded, they have clear right answers more often than therapeutic questions, the evidence base is more structured (package inserts, pharmacology databases, interaction checkers), and clinicians have immediate use for them. Build the pipeline on safety-interaction questions, earn trust, then expand.

**Invest in the retrieval trace UI.** Letting clinicians see what was retrieved, why it was ranked the way it was, and which chunks supported which claim is the feature that turns skeptical clinicians into advocates. It takes real effort. It's worth it.

**Curate, don't just scrape.** A smaller, well-curated corpus with strong metadata beats a larger, messier corpus. Take the 200 most-cited papers in a specialty, the current guidelines, and the current society consensus statements, and start there. Expand deliberately rather than by volume.

**Set expectations honestly in the product.** A banner that says "The corpus contains evidence through April 2026. Recent developments may not be reflected." is not a weakness; it's a trust signal. A disclaimer that says "This synthesis is not a substitute for clinical judgment and should be verified against the cited sources" is not a legal CYA; it's the correct framing. Clinicians who see a product that acknowledges its limits trust the product more, not less.

**Log everything and look at the logs.** The logs tell you what clinicians are actually asking (often different from what you expected). They tell you where validation is failing. They tell you which sources the system keeps trying to use and can't find. Sit down with a week of logs and a clinical reviewer once a month. The surprises in those sessions are where the real improvements come from.

**Don't build this tool in isolation.** Medical librarians are still vastly better at complex literature searches than any RAG system. A library-integrated product (RAG for routine questions, escalation to a medical librarian for complex or high-stakes questions) is usually the right operational design for a health system. The RAG system covers the 80% of questions that it can answer well; the librarian covers the 20% that require human judgment. Pretending the RAG system can replace the librarian is how you end up with both a worse RAG system (because you avoided the escalation path) and an absent librarian service (because the budget went to the AI).

Final thought: this is one of the highest-leverage applications of medical AI I've worked on. A modest-quality literature-search tool saves clinicians minutes per question; at scale, that's millions of clinician-hours a year. It won't replace clinical reasoning. It doesn't need to. It just needs to deliver the right starting point faster than the clinician could get there alone, with enough transparency that the clinician can trust what they're seeing. That's a bar worth clearing.

---

