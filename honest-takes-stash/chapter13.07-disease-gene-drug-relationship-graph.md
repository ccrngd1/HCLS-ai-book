<!-- Removed from chapter13.07-disease-gene-drug-relationship-graph.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what will surprise you when you build this:

**The entity resolution is 60% of the work.** You'll think the hard part is the graph queries or the clinical logic. It's not. It's getting "tamoxifen" from PharmGKB, "DB00675" from DrugBank, and "RxNorm:10324" from your EHR to all point to the same node. Every source has its own identifier system, its own naming conventions, and its own version of "the same thing." You'll spend more time on mapping tables than on graph algorithms.

**Evidence levels are political, not just scientific.** Different organizations classify the same evidence differently. PharmGKB might rate something as "2A" while CPIC hasn't issued a guideline for it yet. The FDA might have it in labeling while CPIC calls it "optional." Your system needs a clear policy on which authority wins, and that policy will be debated by your clinical governance committee for months.

**CYP2D6 alone will make you question your career choices.** This single gene has over 100 defined star alleles, gene deletions, gene duplications, tandem arrangements, and hybrid alleles. The diplotype-to-phenotype translation is not a simple lookup table. It involves activity scores, copy number considerations, and edge cases that even experts disagree on. If your system handles CYP2D6 correctly, everything else is comparatively straightforward.

**Clinicians don't trust black boxes.** If your system says "use alternative therapy" but can't show the reasoning chain (this variant, in this gene, causes this phenotype, which affects this drug, per this guideline, at this evidence level), clinicians will ignore it. Explainability isn't a nice-to-have. It's a requirement for adoption. Every recommendation needs a traceable path through the graph.

**The "last mile" to the EHR is the hardest mile.** You can build a beautiful knowledge graph with perfect evidence grading. But if the alert fires in the EHR at the wrong time, in the wrong format, or without enough context for the clinician to act, it's useless. Integration with clinical workflow (when to alert, who to alert, what action to suggest, how to document the decision) is where most pharmacogenomics implementations stall.

---

