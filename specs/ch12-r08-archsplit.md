---
id: ch12-r08-archsplit
title: 'Polish split: Disease Progression Trajectory Modeling'
target_persona: TechEditor
tags:
- chapter12
- recipe
- split-polish
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter12.08-disease-progression-trajectory-modeling.md
  - chapter12.08-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter12.08
- type: persona_review
  name: standalone-readability
  persona: TechExpertReviewer
  pass_condition: >-
    The main recipe reads as a coherent standalone document (The Problem, The
    Technology, general architecture, The Honest Take) with a working callout to
    the architecture companion and no dangling references to AWS content that
    moved to the companion. The architecture companion reads standalone with a
    backlink to the main recipe and intact pseudocode. No em dashes.
---


## Objective
Polish the split of Disease Progression Trajectory Modeling so both the main recipe and its architecture companion read as coherent standalone documents.

## Instructions
This recipe was mechanically split into chapter12.08-disease-progression-trajectory-modeling.md (story and concepts) and chapter12.08-architecture.md (AWS implementation and pseudocode). Read both files. Fix ONLY transition seams: make sure the main recipe's General Architecture and The Honest Take sections do not dangle references to AWS content that moved to the companion, the architecture callout is well placed, and the architecture companion opens cleanly. Do not rewrite content, do not move sections, do not add new claims. No em dashes.
