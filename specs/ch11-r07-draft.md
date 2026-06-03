---
id: ch11-r07-draft
title: 'Draft: Chronic Disease Management Coach'
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
  - chapter11.07-chronic-disease-management-coach.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter11.07-chronic-disease-management-coach.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 11.7 on Chronic Disease Management Coach.

## Instructions
Write the full recipe covering chronic disease management coach in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
