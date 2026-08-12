<!-- Removed from chapter15.08-chemotherapy-dose-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Let me be direct: this recipe describes something that is not yet deployed anywhere in clinical practice. It's a research architecture. The algorithms work. The engineering is tractable. The clinical validation is the hard part, and it takes years, not months.

The thing that surprised me most when digging into this space: the RL algorithms are not the bottleneck. Conservative offline RL is well-understood and works reliably on clean data. The bottleneck is data quality. Extracting clean treatment trajectories from EHR data is a nightmare of missing values, inconsistent documentation, and temporal misalignment. You'll spend 80% of your time on data engineering and 20% on the actual RL.

The reward function design is where the real clinical judgment lives. Two equally valid reward functions with different toxicity-efficacy tradeoff weights will produce meaningfully different policies. This isn't a bug; it's a feature. But it means you need oncologists deeply involved in the design process, not just reviewing outputs.

The safety constraint layer is the thing that makes this deployable (eventually). Without hard constraints, no oncologist will trust the system. With them, the system can only recommend actions within the bounds of established clinical safety rules. The RL policy optimizes within those bounds, which is exactly the right framing: "given that we won't do anything dangerous, what's the best we can do?"

If I were starting this project today, I'd begin with a single regimen at a single institution, with a retrospective analysis only. Prove the data pipeline works. Prove the policy evaluation shows improvement. Get oncologists to review the recommendations and tell you where they disagree. That feedback loop is worth more than any algorithmic improvement.

---

