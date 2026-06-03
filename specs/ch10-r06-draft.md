---
id: ch10-r06-draft
title: 'Draft: Speech-to-Text for Telehealth Documentation'
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
  - chapter10.06-speech-to-text-telehealth-documentation.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter10.06-speech-to-text-telehealth-documentation.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 10.6 on Speech-to-Text for Telehealth Documentation.

## Instructions
Write the full recipe covering speech-to-text for telehealth documentation in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
