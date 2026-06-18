---
id: ch06-r07-archsplit
title: 'Polish split: Clinical Trial Patient Matching'
target_persona: TechEditor
tags:
- chapter06
- recipe
- split-polish
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter06.07-clinical-trial-patient-matching.md
  - chapter06.07-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter06.07
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
Polish the split of Clinical Trial Patient Matching so both the main recipe and its architecture companion read as coherent standalone documents.

## Instructions
This recipe was mechanically split into chapter06.07-clinical-trial-patient-matching.md (story and concepts) and chapter06.07-architecture.md (AWS implementation and pseudocode). Read both files. Fix ONLY transition seams: make sure the main recipe's General Architecture and The Honest Take sections do not dangle references to AWS content that moved to the companion, the architecture callout is well placed, and the architecture companion opens cleanly. Do not rewrite content, do not move sections, do not add new claims. No em dashes.
