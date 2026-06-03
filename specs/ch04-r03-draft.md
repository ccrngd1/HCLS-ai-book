---
id: ch04-r03-draft
title: 'Draft: Provider Directory Search Optimization'
target_persona: TechWriter
tags:
- chapter04
- recipe
- draft
depends_on:
- ch04-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.03-provider-directory-search-optimization.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter04.03-provider-directory-search-optimization.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Provider Directory Search Optimization.

## Instructions
Write the full recipe covering architecture patterns for provider directory search optimization in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
