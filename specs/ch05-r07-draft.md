---
id: ch05-r07-draft
title: 'Draft: Longitudinal Patient Matching Across Name Changes'
target_persona: TechWriter
tags:
- chapter05
- recipe
- draft
depends_on:
- ch05-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.07-longitudinal-patient-matching-name-changes.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter05.07-longitudinal-patient-matching-name-changes.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Longitudinal Patient Matching Across Name Changes.

## Instructions
Write the full recipe covering architecture patterns for longitudinal patient matching across name changes in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
