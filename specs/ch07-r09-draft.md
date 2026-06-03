---
id: ch07-r09-draft
title: 'Draft: Mortality Risk Scoring ICU'
target_persona: TechWriter
tags:
- chapter07
- recipe
- draft
depends_on:
- ch07-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.09-mortality-risk-scoring-icu.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter07.09-mortality-risk-scoring-icu.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Mortality Risk Scoring ICU.

## Instructions
Write a complete recipe covering Mortality Risk Scoring ICU in healthcare. Include use case description, architecture patterns, hidden challenges, limitations and assumptions, and implementation considerations.
