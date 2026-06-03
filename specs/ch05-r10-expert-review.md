---
id: ch05-r10-expert-review
title: 'Expert Review: Deceased Patient Resolution and Record Reconciliation'
target_persona: TechExpertReviewer
tags:
- chapter05
- recipe
- expert-review
depends_on:
- ch05-r10-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter05.10-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py reviews/chapter05.10-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Deceased Patient Resolution and Record Reconciliation recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that hidden challenges and limitations reflect real-world deployment experience.
