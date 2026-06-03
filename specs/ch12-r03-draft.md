---
id: ch12-r03-draft
title: 'Draft: ED Arrival Forecasting'
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
  - chapter12.03-ed-arrival-forecasting.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter12.03-ed-arrival-forecasting.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 12.3 on ED Arrival Forecasting.

## Instructions
Write the full recipe covering ed arrival forecasting in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
