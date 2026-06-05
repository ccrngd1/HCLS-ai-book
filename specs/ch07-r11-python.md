---
id: ch07-r11-python
title: 'Python Companion: Claim Denial and Prior-Auth Determination Prediction'
target_persona: TechWriter
tags:
- chapter07
- recipe
- python
depends_on:
- ch07-r11-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.11-python-example.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter07.11-python-example.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Python code uses correct boto3 API calls, includes proper error
    handling comments, demonstrates the recipe pattern end-to-end, and has no placeholder
    or stub implementations.
---


## Objective
Create the Python companion for Claim Denial and Prior-Auth Determination
Prediction.

## Instructions
Write a Python example that demonstrates supervised claim-determination
prediction end to end:
- Generate synthetic claims data with realistic fields (CPT/HCPCS code, ICD-10
  code, payer, provider type, place of service, prior-auth flag, claim amount,
  modifiers) and a binary or multi-class determination label, including a
  realistic class imbalance (most claims paid).
- Train a gradient-boosted tree classifier (XGBoost or LightGBM) with a
  logistic-regression baseline for comparison.
- Show appropriate handling of class imbalance and categorical encoding.
- Evaluate with metrics suited to imbalance (precision/recall, PR-AUC, ROC-AUC,
  confusion matrix) rather than raw accuracy.
- Demonstrate explainability with SHAP feature attributions so a flagged claim
  comes with a human-readable reason.
- Show how this would be trained and hosted on Amazon SageMaker (boto3), with
  notes on batch vs real-time scoring.
- Include inline comments and a clear gap-to-production section.
