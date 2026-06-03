---
id: ch03-r08-expert-review
title: 'Expert Review: Readmission Risk Anomaly Detection'
target_persona: TechExpertReviewer
tags:
- chapter03
- recipe
- expert-review
depends_on:
- ch03-r08-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter03.08-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter03.08-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Readmission Risk Anomaly Detection recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that hidden challenges and limitations reflect real-world deployment experience.
