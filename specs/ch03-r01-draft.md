---
id: ch03-r01-draft
title: 'Draft: Duplicate Claim Detection'
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
  - chapter03.01-duplicate-claim-detection.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter03.01-duplicate-claim-detection.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Duplicate Claim Detection.

## Instructions
Write the full recipe covering architecture patterns for duplicate claim detection in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
