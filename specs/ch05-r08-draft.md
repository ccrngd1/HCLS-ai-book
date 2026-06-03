---
id: ch05-r08-draft
title: 'Draft: Privacy-Preserving Record Linkage'
target_persona: TechWriter
tags:
- chapter05
- recipe
- draft
depends_on:
- ch05-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter05.08-privacy-preserving-record-linkage.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter05.08-privacy-preserving-record-linkage.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Privacy-Preserving Record Linkage.

## Instructions
Write the full recipe covering architecture patterns for privacy-preserving record linkage in healthcare. Include use case description, architecture patterns, hidden challenges, and limitations.
