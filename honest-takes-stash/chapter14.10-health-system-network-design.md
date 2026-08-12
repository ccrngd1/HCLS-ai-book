<!-- Removed from chapter14.10-health-system-network-design.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is the most complex recipe in this chapter, and possibly in the entire book. The mathematical formulation is the easy part. The hard parts are:

1. **Getting the data right.** Patient origin analysis requires linking claims, encounters, and geographic data across systems that were never designed to talk to each other. Budget 3-6 months just for data preparation.

2. **Calibrating the gravity model.** If your choice model doesn't match observed behavior, the optimizer will confidently recommend the wrong network configuration. Spend serious time on model validation before trusting the outputs.

3. **Managing the politics.** Every facility has a constituency. Every service line has a physician champion. The optimizer doesn't know about the board member whose family donated the land for the rural hospital. Build the tool to support "what-if" exploration, not to deliver ultimatums.

4. **Dealing with uncertainty honestly.** A 10-year demand forecast is a guess dressed up in statistics. The scenario analysis approach helps, but executives need to understand that "optimal" means "best given these assumptions," not "guaranteed to work."

The part that surprised me most: the minimum volume constraints are often the binding ones. The optimizer wants to spread services across many locations for access, but quality and accreditation requirements force concentration. This tension between access and quality is the fundamental tradeoff in network design, and no amount of optimization eliminates it. It just makes it visible.

One more thing: don't try to solve the whole problem at once on your first iteration. Start with a single service line (e.g., "where should we put our next orthopedic surgery center?") and build confidence in the approach before tackling the full multi-service network design. The single-service version is a useful deliverable on its own and teaches you where your data gaps are.

---

