---
id: ch10-r09-draft
title: 'Draft: Speech Therapy Assessment and Monitoring'
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
  - chapter10.09-speech-therapy-assessment-monitoring.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter10.09-speech-therapy-assessment-monitoring.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 10.9 on Speech Therapy Assessment and Monitoring.

## Instructions
Write the full recipe covering speech therapy assessment and monitoring in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
