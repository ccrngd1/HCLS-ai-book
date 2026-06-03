---
id: ch14-r08-expert-review
title: 'Expert Review: Ambulance Routing and Dispatch'
target_persona: TechExpertReviewer
tags:
- chapter14
- recipe
- expert-review
depends_on:
- ch14-r08-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter14.08-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py reviews/chapter14.08-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Ambulance Routing and Dispatch recipe.

## Instructions
Review for clinical/operational accuracy, architectural soundness, and completeness. Validate that optimization constraints reflect real-world healthcare operations, that the approach scales to production volumes, and that human override mechanisms are appropriately designed.
