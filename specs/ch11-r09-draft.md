---
id: ch11-r09-draft
title: 'Draft: Care Coordination Assistant'
target_persona: TechWriter
tags:
- chapter11
- recipe
- draft
depends_on:
- ch11-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter11.09-care-coordination-assistant.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter11.09-care-coordination-assistant.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 11.9 on Care Coordination Assistant.

## Instructions
Write the full recipe covering care coordination assistant in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
