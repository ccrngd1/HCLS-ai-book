<!-- Removed from chapter14.05-operating-room-block-scheduling.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what nobody tells you about OR block scheduling optimization: the math is the easy part. The solver will happily produce an optimal schedule in 10 minutes. Getting institutional buy-in to actually implement it takes 6-12 months.

The utilization data will reveal uncomfortable truths. Some surgeons are using 40% of their allocated time and have been for years. Some services have blocks on days when their surgeons are in clinic and literally cannot operate. Surfacing these facts creates conflict, and the optimization project gets blamed for the conflict rather than credited for revealing the inefficiency.

My advice: start with a "what-if" tool, not a mandate. Let department chairs explore scenarios: "What happens if we move cardiothoracic from Thursday to Tuesday?" "What if we add a block for robotics?" Let them discover the tradeoffs themselves. Once they trust the model, they'll ask it to suggest the optimal schedule. That transition from "tool" to "authority" is the real deployment milestone.

The block release engine is the quick win. It's non-controversial (nobody loses their allocated blocks), immediately improves utilization, and builds trust in the optimization system. Deploy that first, measure the improvement, then use those results to justify the full scheduling overhaul.

One more thing: the 75% utilization target that every hospital uses as a benchmark is somewhat arbitrary. The "right" utilization depends on your case mix, turnover times, and tolerance for overtime. A 90% utilized OR with frequent overtime cases is not better than a 75% utilized OR that finishes on time every day. Include a utilization ceiling in your constraints, not just a floor.

**Things I'd build next if I had another quarter:**

- **Surgeon preference modeling.** The pseudocode treats services as monolithic units. In reality, individual surgeons within a service have specific day preferences (Dr. Smith operates Tuesday/Thursday; Dr. Jones does Monday/Wednesday/Friday). A production system needs surgeon-level preference data and may need to decompose the problem into service-level block allocation followed by surgeon-level assignment within blocks.
- **Seasonality handling.** Surgical volumes aren't constant. Orthopedics spikes in winter (ski injuries) and summer (elective joint replacements when people can recover before fall). A production forecasting model needs seasonal decomposition, not just rolling averages.
- **Change management workflow.** An optimization output that shows a service losing blocks requires a structured approval workflow: notification to the affected department chair, appeal period, executive sign-off. The technical system needs to integrate with your institutional governance process.
- **Integration with the scheduling system.** The block template must flow into whatever surgical scheduling application your institution uses (Epic OpTime, Cerner SurgiNet, etc.). That integration is institution-specific and often the hardest part of the project. For on-premises EHRs, you'll need a secure private API accessible over a VPN tunnel. For cloud-hosted EHRs, consider private network peering between your optimization environment and the EHR's network.
- **Utilization drift monitoring.** Deploy a monitoring dashboard comparing predicted vs. actual utilization weekly. Alert if any service's actual utilization falls more than 15 percentage points below prediction for two consecutive weeks. This early-warning system lets you investigate and consider mid-quarter adjustments rather than waiting for the next quarterly review.

---

