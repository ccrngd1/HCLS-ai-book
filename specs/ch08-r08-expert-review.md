---
id: ch08-r08-expert-review
title: 'Expert Review: Clinical Assertion Classification'
target_persona: TechExpertReviewer
tags:
- chapter08
- recipe
- expert-review
depends_on:
- ch08-r08-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter08.08-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter08.08-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Clinical Assertion Classification recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the approach is appropriate for healthcare, limitations are acknowledged, and the recipe provides actionable guidance.
