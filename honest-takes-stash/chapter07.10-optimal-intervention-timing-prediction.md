<!-- Removed from chapter07.10-optimal-intervention-timing-prediction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of the hardest problems in healthcare ML, and I want to be upfront about that. Most organizations that attempt optimal timing prediction end up building a really good risk score and calling it a timing model. That's not nothing. A good risk score with a velocity component (is risk rising?) gets you 70% of the value of true timing optimization. But it's not the same thing.

The causal inference piece is where everyone gets stuck. You want to know "if I intervene on day 5, what happens?" but your historical data only shows you what happened when someone did or didn't intervene based on whatever ad hoc criteria they were using at the time. Disentangling the causal effect of intervention timing from the selection bias in who got intervened on and when is genuinely hard. Most teams skip this and use the simpler "rising risk" heuristic. That's a reasonable choice.

The part that surprised me most: intervention fatigue is a bigger deal than most models account for. If you call a patient every week because your model keeps flagging them, they stop answering. The optimal timing model needs to account for its own previous recommendations, which creates a feedback loop that's tricky to handle correctly.

The self-fulfilling prophecy problem is real and insidious. Your model gets better at identifying the right patients at the right time. You intervene. They don't have events. Your next training cycle sees "model flagged, no event" and learns to flag less aggressively. Over 2-3 retraining cycles, the model can degrade significantly. You need a holdout strategy (randomly withhold intervention for a small percentage of flagged patients) to maintain the training signal, and that raises ethical questions about withholding care from patients you believe are at risk.

A few guardrails on holdout designs: they're only appropriate for low-intensity interventions (outreach calls, reminders) where standard of care is already met without the model. IRB review is required for any prospective holdout. Natural variation in care manager capacity creates quasi-experimental conditions without deliberate withholding, and that's often sufficient. Never withhold clinical interventions (medication changes, referrals) for model training purposes.

Start with the hybrid approach: dynamic survival model for trajectory prediction, simple decision rules for timing. Get that working, measure whether it improves outcomes compared to static risk scoring, and only then invest in the full causal/RL approach. The infrastructure you build for the simple version is the same infrastructure the complex version needs.

One more thing: deploy in shadow mode first. Generate recommendations without surfacing them to the care team, and compare against actual care team decisions. Have a clinical advisory board review the threshold settings and decision logic. Run a prospective pilot with defined success metrics (intervention acceptance rate, event prevention rate) before full rollout. The model needs to earn trust before it gets to influence care delivery.

---

