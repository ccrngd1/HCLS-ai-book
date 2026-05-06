---
id: ch11-r04-expert-review
title: "Expert Review: Pre-Visit Intake Bot"
target_persona: TechExpertReviewer
tags: [chapter11, recipe, expert-review]
depends_on: [ch11-r04-draft]
validation:
  - type: file_exists
    name: output-file-exists
    paths: [reviews/chapter11.04-expert-review.md]
  - type: persona_review
    name: quality-review
    persona: TechCodeReviewer
    pass_condition: >-
      Review covers clinical accuracy, architectural soundness, security considerations, and provides prioritized findings (HIGH/MEDIUM/LOW) with concrete remediation steps.
---

## Objective
Perform expert review for recipe 11.4 draft.

## Instructions
Review the draft for technical accuracy, completeness of architecture patterns, and healthcare domain correctness. Validate against real-world healthcare implementations.
