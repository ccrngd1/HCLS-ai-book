---
id: ch06-r07-draft
title: 'Draft: Clinical Trial Patient Matching'
target_persona: TechWriter
tags:
- chapter06
- recipe
- draft
depends_on:
- ch06-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter06.07-clinical-trial-patient-matching.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter06.07-clinical-trial-patient-matching.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Clinical Trial Patient Matching.

## Instructions
Write a complete recipe covering Clinical Trial Patient Matching in healthcare. Include use case description, architecture patterns, hidden challenges, limitations and assumptions, and implementation considerations.
