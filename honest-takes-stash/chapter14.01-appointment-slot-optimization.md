<!-- Removed from chapter14.01-appointment-slot-optimization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of those problems where the math is the easy part. The hard part is getting people to trust the output.

I've seen optimization projects produce templates that are objectively better by every metric, and then watched them die because a provider said "I don't like having 10-minute slots, it feels rushed." The feeling matters. If a provider feels rushed, they'll run over regardless of what the template says, and your optimization is worthless. Build provider preferences into your constraints, not as an afterthought.

The overbooking piece is politically sensitive. "The computer says we should double-book the 9am slot" is a hard sell to a provider who remembers the last time they were double-booked and ran 45 minutes behind all morning. Present it as "the data shows that 9am has a 25% no-show rate, so booking one extra patient at 9am results in the expected panel size, not an overload." Framing matters enormously.

The biggest surprise: the variance in visit duration matters more than the mean. A provider whose visits are consistently 22 minutes (low variance) can be scheduled much more tightly than one whose visits range from 8 to 55 minutes (high variance), even if both have the same average. Most scheduling systems ignore variance entirely. That's where the biggest gains hide.

Start with one willing provider. Show results. Let word spread. Mandating optimized templates across a department without buy-in is a recipe for passive resistance.

---

