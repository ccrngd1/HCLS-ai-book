<!-- Removed from chapter15.09-radiation-therapy-adaptive-planning.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of the most intellectually satisfying applications of RL I've encountered, and also one of the hardest to deploy responsibly.

The fundamental tension: RL is most valuable when it can discover strategies that humans haven't considered. But in radiation therapy, "strategies humans haven't considered" might mean "strategies that are dangerous in ways we don't understand yet." The conservative offline RL approach (CQL, BCQ) addresses this by staying close to historical practice, but that also limits the potential upside. If the policy can only recommend actions similar to what clinicians already do, what's the point?

The point is timing and personalization. Clinicians already know how to replan. They don't always know the optimal moment to replan for a specific patient. The RL agent's value isn't in discovering novel treatment strategies; it's in identifying the right moment to apply known strategies based on patient-specific trajectory data that's hard for humans to integrate across 30+ fractions.

The acceptance rate problem is real. In pilot studies, clinicians override RL recommendations 30-40% of the time. Some of those overrides are because the clinician has information the model doesn't (patient preference, comorbidities not in the state). Some are because the clinician doesn't trust the model yet. Distinguishing these cases is important for improving the system.

The thing that surprised me most: the reward function design takes longer than the RL algorithm implementation. Getting radiation oncologists to agree on the relative importance of TCP vs. NTCP vs. replanning cost, and to express those preferences as numerical weights, is a months-long conversation. And different oncologists have legitimately different preferences. A single reward function may not capture the diversity of reasonable clinical practice.

Start with the simplest version: binary "replan yes/no" recommendations for a single tumor site (head and neck is the most studied). Get the data pipeline working. Get the clinician interface right. Get the feedback loop running. The RL algorithm is the easy part. Everything around it is hard.

One more thing: patient informed consent for AI-assisted treatment planning is an evolving area. Some institutions require explicit disclosure that an AI system contributes to treatment recommendations, while others consider it part of standard clinical decision support that doesn't require separate consent. Check your institution's IRB and legal requirements early.

---

