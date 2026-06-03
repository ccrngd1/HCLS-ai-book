---
id: ch06-r04-draft
title: 'Draft: Disease Severity Stratification'
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
  - chapter06.04-disease-severity-stratification.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter06.04-disease-severity-stratification.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Disease Severity Stratification.

## Instructions
Write a complete recipe covering Disease Severity Stratification in healthcare. Include use case description, architecture patterns, hidden challenges, limitations and assumptions, and implementation considerations.
