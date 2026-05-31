---
id: ch14-r04-expert-review
title: "Expert Review: Nurse Staffing Optimization"
target_persona: TechExpertReviewer
tags: [chapter14, recipe, expert-review]
depends_on: [ch14-r04-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter14.04-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Nurse Staffing Optimization recipe.

## Instructions
Review for clinical/operational accuracy, architectural soundness, and completeness. Validate that optimization constraints reflect real-world healthcare operations, that the approach scales to production volumes, and that human override mechanisms are appropriately designed.
