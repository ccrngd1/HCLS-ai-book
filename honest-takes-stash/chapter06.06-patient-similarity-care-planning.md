<!-- Removed from chapter06.06-patient-similarity-care-planning.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Patient similarity is one of those ideas that sounds obviously useful and is genuinely hard to get right. The first time I built one of these, I spent two weeks tuning the distance metric before realizing my feature set was the actual problem. I was optimizing the wrong thing entirely. The concept is intuitive: find patients like this one, see what worked. The execution is full of subtle traps.

The biggest trap is the assumption that "similar features" implies "similar outcomes." It often does. But sometimes two patients look identical on paper and have wildly different trajectories because of factors you didn't capture: social support, health literacy, genetic variation, provider quality. Your similarity metric is only as good as your features, and your features are only as good as your data capture.

The second trap is sample size. For common conditions in large health systems, you'll find plenty of similar patients. For rare conditions, complex multi-morbidity patterns, or small health systems, the cohort might be 3 patients. Presenting aggregated outcomes from 3 patients as if they're statistically meaningful is dangerous. The system must communicate uncertainty honestly.

The thing that surprised me most: clinicians don't want a black box that says "do this." They want a tool that says "here's what happened to patients like yours, here's what was tried, here's what worked and what didn't." The decision remains theirs. The system provides evidence. That framing (decision support, not decision making) is both ethically correct and practically necessary for adoption.

Start with a single condition (diabetes is the classic choice: large population, well-defined outcomes, measurable goals). Validate that your similarity metric actually predicts outcome similarity before expanding. And involve clinicians in feature selection from day one. The features that matter are not always the features that are easy to compute.

---

