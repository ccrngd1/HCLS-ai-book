# Open TODOs — Recipe 7.3: Patient Churn / Disenrollment Prediction

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.03-patient-churn-disenrollment-prediction.md`

- **L108** — TODO (TechWriter): Expert review A1 (MEDIUM). Add a Step 6 for model monitoring: monthly ground truth join comparing predictions from 90 days ago against actual disenrollment outcomes, rolling AUC-PR and ECE computation published to CloudWatch, retraining trigger when AUC-PR drops below 0.40 or ECE exceeds 0.10. Especially important around open enrollment periods when population composition shifts.

## architecture — `chapter07.03-architecture.md`

- **L367** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add content covering gaps a production deployment must close (e.g., model monitoring, fairness audits, retraining automation, integration testing with intervention systems).
