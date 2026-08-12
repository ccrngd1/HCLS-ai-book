<!-- Removed from chapter08.07-adverse-event-detection-clinical-text.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what actually happens when you deploy adverse event detection in a health system.

The first week, the safety team is drowning. Every note that mentions a symptom near a medication gets flagged. Expected side effects dominate the output. Your pharmacovigilance team, who previously reviewed maybe 20 voluntary reports a month, is now looking at 500 automated detections a week. Most are noise.

The fix is iterative tuning of the expected-effects filter. You need a comprehensive "known and expected" database that you maintain by drug class. Statins cause myalgia. SSRIs cause GI upset. Beta-blockers cause fatigue. None of these are novel safety signals. Filter them out of the alert stream (but keep them in the database for aggregation, because a higher-than-expected rate of a "known" effect can still be a signal).

The hardest false negatives to address are the implicit mentions. "Patient feels worse since last visit" is potentially an adverse event if a new medication was started at the last visit. But connecting "feels worse" to a specific drug requires reasoning across notes, not just within a single note. Cross-note reasoning is architecturally expensive and introduces complexity that most first-generation systems skip. Plan for it in your roadmap but don't try to build it first.

The aggregation step is where the real value emerges, and it takes months. You need a critical mass of processed notes before disproportionality analysis becomes meaningful. In a health system processing 10,000 notes per day, you'll start seeing reliable signals after 2-3 months of operation. Smaller systems need longer. This means your stakeholders need patience, which is not a technology problem but is absolutely a deployment challenge.

One thing that surprised me: the highest-value outputs weren't the individual high-severity alerts (those tend to be caught anyway through existing clinical workflows). The highest value was in moderate-severity events that individually seemed unremarkable but in aggregate revealed a real pattern. Fourteen patients with mild dizziness on the same medication formulation, from the same manufacturer, dispensed in the same quarter. That's a signal that no voluntary reporting system would ever surface.

---

