---
id: ch03-r02-draft
title: 'Draft: Patient No-Show Pattern Detection'
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
  - chapter03.02-patient-no-show-pattern-detection.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter03.02-patient-no-show-pattern-detection.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Patient No-Show Pattern Detection.

## Instructions
Write the full recipe covering architecture patterns for patient no-show pattern detection in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
