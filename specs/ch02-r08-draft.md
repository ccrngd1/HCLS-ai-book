---
id: ch02-r08-draft
title: 'Draft: Ambient Clinical Documentation'
target_persona: TechWriter
tags:
- chapter02
- recipe
- draft
depends_on:
- ch02-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.08-ambient-clinical-documentation.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter02.08-ambient-clinical-documentation.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Ambient Clinical Documentation.

## Instructions
Write the full recipe covering architecture patterns for ambient clinical documentation in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
