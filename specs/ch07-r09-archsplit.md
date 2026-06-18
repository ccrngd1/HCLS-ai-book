---
id: ch07-r09-archsplit
title: 'Polish split: Mortality Risk Scoring Icu'
target_persona: TechEditor
tags:
- chapter07
- recipe
- split-polish
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter07.09-mortality-risk-scoring-icu.md
  - chapter07.09-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter07.09
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
Polish the split of Mortality Risk Scoring Icu so both the main recipe and its architecture companion read as coherent standalone documents.

## Instructions
This recipe was mechanically split into chapter07.09-mortality-risk-scoring-icu.md (story and concepts) and chapter07.09-architecture.md (AWS implementation and pseudocode). Read both files. Fix ONLY transition seams: make sure the main recipe's General Architecture and The Honest Take sections do not dangle references to AWS content that moved to the companion, the architecture callout is well placed, and the architecture companion opens cleanly. Do not rewrite content, do not move sections, do not add new claims. No em dashes.
