<!-- Removed from chapter15.03-clinical-trial-adaptive-randomization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The math here is genuinely elegant. Thompson Sampling for clinical trials is one of those ideas that feels obviously right once you understand it. The implementation is not that hard either. A Beta-Binomial model with Thompson Sampling is maybe 50 lines of core logic.

What's hard is everything around the algorithm:

**The simulation studies take months.** Before you can run an adaptive trial, you need to simulate it under dozens of scenarios (different true effect sizes, different enrollment rates, different dropout patterns) and demonstrate that your Type I error is controlled and your power is adequate. This is a biostatistician's job, not a software engineer's, and it takes 3-6 months of careful work.

**The regulatory package is substantial.** You're not just submitting a protocol. You're submitting the adaptation algorithm, the simulation results, the operating characteristics, and a justification for why adaptive randomization is appropriate for this specific trial. The FDA will review all of it.

**Operational complexity is real.** Your EDC system needs to integrate with the randomization service. Outcome data needs to flow reliably and promptly. Sites need training on the adaptive design. The DSMB needs access to unblinded allocation data. The randomization service needs to be available 24/7 because sites enroll patients at all hours.

**The sample size savings are often modest.** In the literature, you'll see claims of 20-40% sample size reduction. In practice, for well-powered trials with moderate effect sizes, the savings are often 10-20%. The ethical benefit (fewer patients on inferior arms) is real but harder to quantify in a regulatory submission.

The part that surprised me: the biggest resistance isn't technical or regulatory. It's cultural. Investigators are trained on fixed randomization. Biostatisticians are comfortable with standard analyses. Introducing adaptive designs requires educating the entire trial team, and that education effort is often underestimated.

Start with a trial where the ethical case is strong (rare disease, high unmet need, large expected effect size) and where the sponsor has experience with adaptive designs. Don't make your first adaptive trial a pivotal Phase III registration study.

---

