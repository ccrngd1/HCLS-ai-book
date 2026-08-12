<!-- Removed from chapter02.10-multi-modal-clinical-reasoning.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Multi-modal clinical reasoning is the use case where the gap between capability demos and deployed reality is widest. The demos are compelling. The benchmarks on curated sets are often strong. The production reality is harder than it looks, and the failure modes hurt patients in specific and occasionally subtle ways. Anyone building this should start from the assumption that they are building a medical device by another name, and that the care with which they build it matters.

A few things that are true, said plainly.

**Start with the narrowest possible scope.** The temptation to build a general reasoner is strong and wrong. The teams that have succeeded in pilot deployments have scoped to very specific clinical situations: dyspnea in the ED, oncology treatment selection for a specific cancer, heart failure readmission risk review. Narrow scope makes validation feasible, makes the UX designable, makes the regulatory posture defensible, and makes clinician engagement earnable. Breadth is a future problem.

**Build on cleared components where possible.** If your pipeline depends on imaging AI outputs, use FDA-cleared products within their cleared scope. If it depends on ECG interpretations, use the machine interpretations plus cleared models where available. The reasoning layer over cleared inputs is more defensible than a reasoning layer that also produces diagnostic impressions from pixels.

**Enforce grounding ferociously.** Every quantitative value, every graded term, every drug name, every dose in the output must appear verbatim in a cited source. Every recommendation must carry explicit citations. Every claim must be verifiable. Validation is the belt to Guardrails' suspenders. Omit either and the hallucination rate climbs to levels that will cause patient-facing harm.

**Make reasoning visible in the UI.** The clinician needs to see the evidence for and against each hypothesis with sources one click away. If the UI foregrounds conclusions with reasoning tucked behind, clinicians under time pressure will skip the reasoning and act on the conclusions. That path loses the CDS exemption and trust at the same time.

**Acknowledge missing and stale modalities explicitly.** The reasoning output should say what is absent that is relevant and what is old that may have changed. A reasoning output that presents a confident conclusion without acknowledging its data limitations is misleading in a way that looks helpful, which is the worst kind of misleading.

**Budget time for clinical validation you cannot skip.** Expert clinical review of curated scenarios is the main rate-limiter for expanding scope. Domain experts are scarce, their time is expensive, and the review is cognitively demanding. A realistic schedule reserves four to eight weeks per scenario per reviewer. Parallelize reviewers when possible; do not short-circuit the process.

**Commit to post-market surveillance.** The day you deploy is not the day you finish. Outcomes data, engagement data, override patterns, demographic subgroup performance, cross-modality consistency metrics, specific error categorizations: these are the inputs to the next iteration. Most deployments under-invest here; the ones that succeed treat it as half the work.

**Do not conflate fluency with correctness.** A well-written reasoning output looks authoritative. A well-written and wrong reasoning output is still wrong. Do not trust the model's eloquence. Trust the validation layer and the clinician's review.

**Keep the clinician the decision-maker.** The value of multi-modal reasoning is faster access to the relevant parts of a patient's record and a second pass through possible explanations, not autonomous decision-making. The product design, the framing in every piece of output, the UX at every engagement point, and the regulatory posture all have to consistently treat the clinician as the agent who decides. The moment any of these drifts toward "the system decides," the product has crossed a line that it should not cross.

One more thing, a personal note. The patients who benefit from this the most are the complicated ones: long histories across several specialties, multiple modalities of data, subtle temporal trajectories, time-pressured clinicians who cannot hold the whole picture in their head. These are exactly the patients who experience the most documentation-driven failures in the current system. Getting this right is not a technical curiosity; it is a meaningful improvement in how care is delivered. Getting it wrong, correspondingly, hurts the patients who need it most. Build like it matters.

---

