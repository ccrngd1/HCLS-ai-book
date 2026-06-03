---
id: ch05-r04-draft
title: 'Draft: Insurance Eligibility Matching'
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
  - chapter05.04-insurance-eligibility-matching.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter05.04-insurance-eligibility-matching.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Insurance Eligibility Matching.

## Instructions
Write the full recipe covering architecture patterns for insurance eligibility matching in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
