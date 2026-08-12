<!-- Removed from chapter02.03-clinical-documentation-improvement.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

CDI is one of those problems where the AI part is actually the easy part. Getting a model to identify specificity gaps in clinical notes is straightforward with modern LLMs. The hard parts are everything around it: EHR integration, physician workflow, compliance review, alert fatigue management, and organizational change management.

The 70-85% accuracy range for suggestions sounds mediocre until you compare it to the alternative: most notes never getting CDI review at all. A system that reviews 100% of notes at 75% accuracy catches more real gaps than a human team that reviews 15% of notes at 95% accuracy. The math works in your favor even with imperfect AI.

The thing that surprised me most: physician acceptance rates are highly sensitive to suggestion phrasing, not suggestion accuracy. A technically correct suggestion phrased poorly ("Documentation deficiency: heart failure type not specified") gets rejected. The same suggestion phrased respectfully ("The echo shows EF 35%. Would you characterize this as systolic heart failure?") gets accepted. Invest heavily in prompt engineering for the query generation step. It matters more than the gap detection step.

Alert fatigue is your biggest operational risk. Start with a high confidence threshold and low maximum suggestions per note. It's better to catch 50% of gaps with high physician trust than to catch 90% of gaps while physicians learn to ignore your system entirely. You can always lower the threshold once you've established credibility.

One more thing: the financial ROI on CDI is easy to measure (compare DRG weights before and after), which makes this one of the easier AI projects to get funded. But don't lead with revenue. Lead with documentation accuracy and patient safety (accurate documentation supports better care transitions). The revenue follows naturally from accurate documentation.

---

