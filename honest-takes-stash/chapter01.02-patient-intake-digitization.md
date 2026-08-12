<!-- Removed from chapter01.02-patient-intake-digitization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The async pattern is architecturally more complex than the synchronous call from Recipe 1.1, but don't let that scare you. The event-driven model is actually quite clean once you've built it: two small functions with one-thing-each responsibility, connected by a notification. It's easier to debug than you might expect because each function has a narrow scope. (For the specific AWS services and their quirks, see the [Architecture companion](chapter01.02-architecture).)

The thing that will surprise you is the service-to-service credential setup. In the async pattern, the extraction service needs its own dedicated identity to push completion signals to your notification channel. It cannot piggyback on your orchestration function's credentials. This trips up every team at least once because most cloud services share the caller's permissions implicitly. You'll know you got it wrong when jobs submit successfully but completion callbacks never arrive. The fix is always the same: grant the extraction service a scoped credential with publish-only access to your notification channel, and give your orchestration function permission to delegate that credential at job submission time. (The [Architecture companion](chapter01.02-architecture) spells out the exact IAM roles and policies for the AWS implementation.)

Table parsing is more reliable than I expected for printed forms. The failure mode isn't random errors in cells; it's structural: entire rows occasionally get merged together, especially when table lines are faint in the scan. The solution is scan quality, not code changes. A decent document scanner at 300 DPI produces much better results than a phone photograph of a paper form.

Checkbox detection is the pleasant surprise. I expected it to be the weakest part of this recipe and it ended up being the most reliable. Modern extraction services correctly classify selected vs. unselected at 97-99% accuracy for standard printed checkboxes. The failure cases are mostly unusual marking styles (patients who put a number rather than an X, or who circled the entire question instead of the box). You'll see these in your flagged fields, which is the right outcome.

The honest scope boundary: this recipe handles printed text well and checkboxes well. It handles tables reasonably well. It handles handwriting with a shrug and an honest confidence score. If your patient population trends toward handwritten completion (older patients in some demographics tend to fill forms in cursive), your flagged field rate will be higher than the benchmarks above. That's not a failure; that's the confidence gating doing its job. Build the review queue from Recipe 1.6 before you go to production.

---

