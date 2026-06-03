---
id: ch11-r05-draft
title: 'Draft: Insurance Benefits Navigator'
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
  - chapter11.05-insurance-benefits-navigator.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter11.05-insurance-benefits-navigator.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft recipe 11.5 on Insurance Benefits Navigator.

## Instructions
Write the full recipe covering insurance benefits navigator in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations/assumptions.
