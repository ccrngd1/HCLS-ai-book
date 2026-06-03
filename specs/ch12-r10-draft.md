---
id: ch12-r10-draft
title: 'Draft: Physiological Waveform Analysis'
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
  - chapter12.10-physiological-waveform-analysis.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter12.10-physiological-waveform-analysis.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 12.10 on Physiological Waveform Analysis.

## Instructions
Write the full recipe covering physiological waveform analysis in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
