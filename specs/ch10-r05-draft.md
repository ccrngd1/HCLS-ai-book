---
id: ch10-r05-draft
title: 'Draft: Patient-Facing Voice Assistant'
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
  - chapter10.05-patient-facing-voice-assistant.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter10.05-patient-facing-voice-assistant.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 10.5 on Patient-Facing Voice Assistant.

## Instructions
Write the full recipe covering patient-facing voice assistant in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
