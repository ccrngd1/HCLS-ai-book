<!-- Removed from chapter02.01-patient-message-response-drafting.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is one of the highest-ROI LLM applications in healthcare right now, and it's also one of the most straightforward to build safely. The human-in-the-loop design means your failure mode is "provider spends 30 seconds editing a draft" rather than "patient receives dangerous medical advice." That's a good failure mode to have.

The part that surprised me: the intent classification step matters more than the model choice. A perfectly generated response to the wrong interpretation of the message is useless. Spend time on your classification logic and on handling ambiguous messages gracefully (when in doubt, classify as "general" and let the model work from the message text alone rather than pulling potentially irrelevant context).

The approval rate is your north star metric. If providers are approving 70%+ of drafts without edits, you're saving real time. If that number drops below 50%, something is wrong: either your prompts have drifted, your context assembly is pulling stale data, or the message mix has shifted toward more complex cases that need manual responses.

Provider-specific tone tuning is worth the effort. Dr. Martinez signs off with "Take care." Dr. Patel uses "Best regards." Dr. Chen is more informal and uses the patient's first name in the greeting. These small details are what make the draft feel like it came from the provider rather than from a machine. Without them, providers will edit every single draft just to add their personal touch, and your approval rate will tank.

The biggest operational headache: keeping the EHR context integration working. Patient data changes constantly. Medications get added and discontinued. Appointments get rescheduled. If your context assembly is pulling from a stale cache rather than live data, the model will reference medications the patient stopped taking two weeks ago. The provider catches it, but it erodes trust in the system.

One more thing: resist the temptation to expand scope. "If it works for refill requests, let's use it for clinical questions too!" No. The safety profile changes dramatically when the message requires clinical judgment. Keep the scope narrow, keep the approval rate high, and expand deliberately.

---

