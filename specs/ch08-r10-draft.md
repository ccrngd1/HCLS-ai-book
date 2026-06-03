---
id: ch08-r10-draft
title: 'Draft: Phenotype Extraction for Research'
target_persona: TechWriter
tags:
- chapter08
- recipe
- draft
depends_on:
- ch08-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter08.10-phenotype-extraction-research.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter08.10-phenotype-extraction-research.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Phenotype Extraction for Research.

## Instructions
Write a complete recipe covering Phenotype Extraction for Research in healthcare. Include use case description, architecture patterns, hidden challenges, limitations and assumptions, and implementation considerations.
