---
id: ch11-r04-draft
title: 'Draft: Pre-Visit Intake Bot'
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
  - chapter11.04-pre-visit-intake-bot.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter11.04-pre-visit-intake-bot.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 11.4 on Pre-Visit Intake Bot.

## Instructions
Write the full recipe covering pre-visit intake bot in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
