---
id: ch02-r10-draft
title: 'Draft: Multi-Modal Clinical Reasoning'
target_persona: TechWriter
tags:
- chapter02
- recipe
- draft
depends_on:
- ch02-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.10-multi-modal-clinical-reasoning.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter02.10-multi-modal-clinical-reasoning.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Multi-Modal Clinical Reasoning.

## Instructions
Write the full recipe covering architecture patterns for multi-modal clinical reasoning in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
