---
id: ch15-r08-expert-review
title: 'Expert Review: Chemotherapy Dose Optimization'
target_persona: TechExpertReviewer
tags:
- chapter15
- recipe
- expert-review
depends_on:
- ch15-r08-draft
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - reviews/chapter15.08-expert-review.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py reviews/chapter15.08-expert-review.md
- type: persona_review
  name: quality-review
  persona: TechCodeReviewer
  pass_condition: Review covers clinical accuracy, architectural soundness, security
    considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete
    remediation steps.
---


## Objective
Provide expert review of the Chemotherapy Dose Optimization recipe.

## Instructions
Review for clinical accuracy, architectural soundness, and completeness. Validate that the RL formulation is clinically appropriate, safety constraints are sufficient, that offline evaluation methodology is sound, and that regulatory considerations (FDA) are adequately addressed.
