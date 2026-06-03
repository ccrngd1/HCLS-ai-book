---
id: ch08-r03-draft
title: 'Draft: ICD-10 Code Suggestion'
target_persona: TechWriter
tags:
- chapter08
- recipe
- draft
depends_on:
- ch08-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter08.03-icd-10-code-suggestion.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter08.03-icd-10-code-suggestion.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for ICD-10 Code Suggestion.

## Instructions
Write a complete recipe covering ICD-10 Code Suggestion in healthcare. Include use case description, architecture patterns, hidden challenges, limitations and assumptions, and implementation considerations.
