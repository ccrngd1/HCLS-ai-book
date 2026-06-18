---
id: ch10-r03-archsplit
title: 'Polish split: Voice To Text Ehr Navigation'
target_persona: TechEditor
tags:
- chapter10
- recipe
- split-polish
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter10.03-voice-to-text-ehr-navigation.md
  - chapter10.03-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter10.03
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
Polish the split of Voice To Text Ehr Navigation so both the main recipe and its architecture companion read as coherent standalone documents.

## Instructions
This recipe was mechanically split into chapter10.03-voice-to-text-ehr-navigation.md (story and concepts) and chapter10.03-architecture.md (AWS implementation and pseudocode). Read both files. Fix ONLY transition seams: make sure the main recipe's General Architecture and The Honest Take sections do not dangle references to AWS content that moved to the companion, the architecture callout is well placed, and the architecture companion opens cleanly. Do not rewrite content, do not move sections, do not add new claims. No em dashes.
