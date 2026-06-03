---
id: ch12-r07-draft
title: 'Draft: Vital Sign Trajectory Monitoring'
target_persona: TechWriter
tags:
- chapter12
- recipe
- draft
depends_on:
- ch12-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter12.07-vital-sign-trajectory-monitoring.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter12.07-vital-sign-trajectory-monitoring.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 12.7 on Vital Sign Trajectory Monitoring.

## Instructions
Write the full recipe covering vital sign trajectory monitoring in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
