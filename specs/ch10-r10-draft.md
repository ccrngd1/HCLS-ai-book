---
id: ch10-r10-draft
title: 'Draft: Multilingual Real-Time Medical Interpretation'
target_persona: TechWriter
tags:
- chapter10
- recipe
- draft
depends_on:
- ch10-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter10.10-multilingual-realtime-medical-interpretation.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter10.10-multilingual-realtime-medical-interpretation.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 10.10 on Multilingual Real-Time Medical Interpretation.

## Instructions
Write the full recipe covering multilingual real-time medical interpretation in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
