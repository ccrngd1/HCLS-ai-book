---
id: ch05-r01-draft
title: 'Draft: Internal Duplicate Patient Detection'
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
  - chapter05.01-internal-duplicate-patient-detection.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter05.01-internal-duplicate-patient-detection.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Internal Duplicate Patient Detection.

## Instructions
Write the full recipe covering architecture patterns for internal duplicate patient detection in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
