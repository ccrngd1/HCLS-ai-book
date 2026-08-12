<!-- Removed from chapter06.02-utilization-pattern-segmentation.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Utilization pattern segmentation is one of the most immediately useful things you can build in population health analytics. The segments are intuitive, the data is available, and the operational applications are obvious. A care management director who sees "11% of your members are disengaged diabetics" knows exactly what to do with that information.

That said, here's what will humble you:

**The "so what?" problem.** Producing segments is easy. Getting the organization to actually change its behavior based on them is hard. If the outreach team is going to send the same letter to every segment, you wasted your time. The segmentation only matters if it drives differentiated action. Start with the operational question ("what would we do differently for each group?") and work backward to the segmentation design.

**Segment instability around the edges.** Members near the boundaries between segments will flip back and forth between runs. A member at the border of "chronic managed" and "moderate episodic" might be in one segment in January and the other in April. This is mathematically expected but operationally annoying. Care managers hate it when their panel changes every month. Solutions: add hysteresis (require a member to meet the new segment criteria for two consecutive runs before migrating) or use GMMs and report the probability rather than a hard assignment.

**The denominator problem.** What counts as "your population"? Active members only? Include members who were active for part of the lookback but termed? Include members who enrolled mid-period (and therefore have less utilization simply because they had less time)? The denominator choice changes your segments. A member with 2 ED visits in 3 months of enrollment looks like a frequent flyer; that same member with 2 ED visits in 24 months of enrollment looks normal.

**Cost features are a trap.** If you include total cost as a clustering feature, it will dominate everything. Cost is correlated with almost every other utilization feature, and its magnitude dwarfs everything else even after normalization. You'll end up with cost quartiles, not behavioral segments. The disciplined approach: cluster on *utilization patterns* (types of services, frequencies, temporal distribution), then analyze cost *within* the resulting segments as a descriptive characteristic.

**The equity audit you can't skip.** Before you operationalize any segmentation, run demographics by segment. If your "disengaged" segment is 60% Black patients while your overall population is 25% Black, that's not a behavioral finding. That's a system access finding. "Disengaged" might really mean "historically excluded from accessible care." The intervention for that group isn't a reminder postcard; it's addressing the structural barriers. Every segmentation needs this check before deployment.

---

