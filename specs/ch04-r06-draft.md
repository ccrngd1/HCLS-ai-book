---
id: ch04-r06-draft
title: 'Draft: Care Gap Prioritization'
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
  - chapter04.06-care-gap-prioritization.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter04.06-care-gap-prioritization.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Care Gap Prioritization.

## Instructions
Write the full recipe covering architecture patterns for care gap prioritization in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
