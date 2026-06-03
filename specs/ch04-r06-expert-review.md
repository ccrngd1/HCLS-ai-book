---
id: ch04-r06-expert-review
title: 'Expert Review: Care Gap Prioritization'
target_persona: TechExpertReviewer
tags:
- chapter04
- recipe
- expert-review
depends_on:
- ch04-r06-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter04.06-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter04.06-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Care Gap Prioritization recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that hidden challenges and limitations reflect real-world deployment experience.
