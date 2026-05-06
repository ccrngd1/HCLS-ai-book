---
id: ch14-r06-expert-review
title: "Expert Review: Patient Flow Bed Assignment"
target_persona: TechExpertReviewer
tags: [chapter14, recipe, expert-review]
depends_on: [ch14-r06-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter14.06-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Provide expert review of the Patient Flow Bed Assignment recipe.

## Instructions
Review for clinical/operational accuracy, architectural soundness, and completeness. Validate that optimization constraints reflect real-world healthcare operations, that the approach scales to production volumes, and that human override mechanisms are appropriately designed.
