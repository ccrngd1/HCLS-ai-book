---
id: ch03-r07-draft
title: 'Draft: Patient Deterioration Early Warning'
target_persona: TechWriter
tags:
- chapter03
- recipe
- draft
depends_on:
- ch03-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter03.07-patient-deterioration-early-warning.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter03.07-patient-deterioration-early-warning.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Patient Deterioration Early Warning.

## Instructions
Write the full recipe covering architecture patterns for patient deterioration early warning in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
