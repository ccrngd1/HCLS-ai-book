---
id: ch10-r02-draft
title: 'Draft: Voicemail Transcription and Classification'
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
  - chapter10.02-voicemail-transcription-classification.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter10.02-voicemail-transcription-classification.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 10.2 on Voicemail Transcription and Classification.

## Instructions
Write the full recipe covering voicemail transcription and classification in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
