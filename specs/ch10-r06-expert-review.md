---
id: ch10-r06-expert-review
title: 'Expert Review: Speech-to-Text for Telehealth Documentation'
target_persona: TechExpertReviewer
tags:
- chapter10
- recipe
- expert-review
depends_on:
- ch10-r06-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter10.06-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter10.06-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Perform expert review for recipe 10.6 draft.

## Instructions
Review the draft for technical accuracy, completeness of architecture patterns, and healthcare domain correctness. Validate against real-world healthcare implementations.
