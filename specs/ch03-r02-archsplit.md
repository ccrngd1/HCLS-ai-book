---
id: ch03-r02-archsplit
title: 'Polish split: Patient No Show Pattern Detection'
target_persona: TechEditor
tags:
- chapter03
- recipe
- split-polish
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter03.02-patient-no-show-pattern-detection.md
  - chapter03.02-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter03.02
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
Polish the split of Patient No Show Pattern Detection so both the main recipe and its architecture companion read as coherent standalone documents.

## Instructions
This recipe was mechanically split into chapter03.02-patient-no-show-pattern-detection.md (story and concepts) and chapter03.02-architecture.md (AWS implementation and pseudocode). Read both files. Fix ONLY transition seams: make sure the main recipe's General Architecture and The Honest Take sections do not dangle references to AWS content that moved to the companion, the architecture callout is well placed, and the architecture companion opens cleanly. Do not rewrite content, do not move sections, do not add new claims. No em dashes.
