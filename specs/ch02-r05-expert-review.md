---
id: ch02-r05-expert-review
title: 'Expert Review: After-Visit Summary Generation'
target_persona: TechExpertReviewer
tags:
- chapter02
- recipe
- expert-review
depends_on:
- ch02-r05-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter02.05-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter02.05-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the After-Visit Summary Generation recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that hidden challenges and limitations reflect real-world deployment experience.
