---
id: ch06-r01-expert-review
title: 'Expert Review: Geographic Patient Clustering'
target_persona: TechExpertReviewer
tags:
- chapter06
- recipe
- expert-review
depends_on:
- ch06-r01-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter06.01-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py reviews/chapter06.01-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Geographic Patient Clustering recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the approach is appropriate for healthcare, limitations are acknowledged, and the recipe provides actionable guidance.
