---
id: ch07-r11-draft
title: 'Draft: Claim Denial and Prior-Auth Determination Prediction'
target_persona: TechWriter
tags:
- chapter07
- recipe
- draft
depends_on:
- ch07-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.11-claim-denial-prediction.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter07.11-claim-denial-prediction.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Claim Denial and Prior-Auth Determination Prediction.

## Instructions
Write a complete recipe covering how to predict the final determination of a
healthcare claim or prior-authorization request (for example: paid vs denied,
or approve / deny / pend) using traditional supervised machine learning.

Frame this explicitly as a supervised classification problem, not clustering:
the outcome is a known categorical label and there is abundant labeled
historical data (past adjudicated claims / determinations). Briefly note that
unsupervised methods like clustering are complementary (denial-reason
segmentation, feature discovery) but are not the core predictor.

Cover at minimum:
- The Problem: denial rates of 10-15%, rework cost per claim ($25-118), the
  value of predicting determinations before submission, and the difference
  between a provider predicting a payer's decision versus a payer building its
  own adjudication model.
- The Technology (vendor-agnostic): gradient-boosted trees (XGBoost /
  LightGBM) as the workhorse, with logistic regression and random forest as
  baselines; why tabular models beat deep learning here; the central role of
  explainability (SHAP) because every flagged claim needs a defensible reason.
- Features: CPT/HCPCS procedure codes, ICD-10 diagnosis codes,
  diagnosis-procedure pairs, payer ID and payer-specific rules, provider type
  and historical denial rate, place of service, prior-auth status, claim
  amount, modifiers, patient demographics and coverage details.
- The three lifecycle prediction points: pre-visit (eligibility / PA risk),
  pre-billing (coding errors), and post-submission (payer behavior).
- General architecture and an AWS implementation (SageMaker for training and
  hosting, feature pipeline, batch and real-time scoring) with a pseudocode
  walkthrough.
- The Honest Take: severe class imbalance, the bias risk of a model that learns
  to predict (and could perpetuate) inappropriate denials, regulatory and
  fairness considerations, and the need for human review of flagged claims.
- Variations, Related Recipes (link to 7.1 no-show, 7.2 propensity-to-pay,
  1.4 prior-auth document processing, 1.5 claims attachment processing), and
  navigation links.

Match the voice and structure of the other Chapter 7 recipes.
