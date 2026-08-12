<!-- Removed from chapter07.09-mortality-risk-scoring-icu.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This is the recipe I'm most conflicted about writing. The technology works. Gradient boosted trees on structured ICU data genuinely outperform APACHE and SOFA for discrimination, and with proper calibration they produce honest probabilities. The infrastructure is straightforward. The math is well-understood.

The hard part is everything around the model. Who sees the score? When? How is it framed? What decisions does it influence? A mortality probability displayed prominently on a patient's chart changes behavior in ways that are difficult to measure and impossible to fully control. A nurse who sees "82% mortality risk" may unconsciously deprioritize that patient's comfort measures. A family who hears "the computer says 70%" may anchor on that number in ways that override nuanced clinical discussion.

The self-fulfilling prophecy problem is real and unsolved. If your model influences transitions to comfort care, and those patients die (as expected when aggressive treatment is withdrawn), your model looks accurate in retrospect. But you can't know what would have happened with continued aggressive care. The honest answer is: we don't know, and we should be transparent about that limitation with every stakeholder.

Calibration drift is the operational challenge that will consume the most ongoing effort. Patient populations change. Treatment patterns evolve. New therapies shift survival curves. A model calibrated in January may be miscalibrated by June. Monthly recalibration is the minimum; continuous monitoring with automated alerts is better.

The thing that surprised me most: clinicians don't want a single number. They want to know why. "68% mortality" is less useful than "68% mortality, primarily driven by worsening organ failure trajectory and escalating vasopressor requirements." The explainability layer (SHAP values translated to plain language) is not a nice-to-have. It's the difference between a tool clinicians trust and one they ignore.

Start with quality benchmarking (risk-adjusted mortality rates for your ICU) before attempting real-time clinical decision support. The benchmarking use case has lower stakes, builds institutional familiarity with the model, and generates the outcome data you need for calibration. Real-time bedside predictions are the end state, not the starting point.

---

