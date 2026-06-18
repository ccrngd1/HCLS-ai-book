---
id: ch11-r10-archsplit
title: 'Bespoke split: Clinical Trial Recruitment Conversationalist'
target_persona: TechEditor
tags:
- chapter11
- recipe
- split-bespoke
depends_on: []
validation:
- type: file_exists
  name: both-files-exist
  paths:
  - chapter11.10-clinical-trial-recruitment-conversationalist.md
  - chapter11.10-architecture.md
- type: shell
  name: structural-check
  commands:
  - python3 check_split.py chapter11.10
- type: persona_review
  name: standalone-readability
  persona: TechExpertReviewer
  pass_condition: >-
    The main recipe contains only vendor-agnostic story and concepts (The
    Problem, The Technology, general architecture), The Honest Take, Related
    Recipes, and Tags, plus a callout to the architecture companion. The
    architecture companion contains the AWS implementation, pseudocode,
    variations, resources, and estimated time, with a backlink to the main
    recipe. No AWS content remains in the main file. No em dashes.
---


## Objective
Split Clinical Trial Recruitment Conversationalist into a main recipe (story and concepts) and a chapter11.10-architecture.md companion (AWS implementation and pseudocode). This recipe does NOT follow the standard heading scheme, so it needs manual judgment rather than the mechanical splitter.

## Instructions
Read chapter11.10-clinical-trial-recruitment-conversationalist.md. It has non-standard section headings and may contain leftover review scaffolding. Split it into two files:
1. chapter11.10-clinical-trial-recruitment-conversationalist.md keeps: The Problem, The Technology, any vendor-agnostic general architecture, The Honest Take, Related Recipes, Tags, and the navigation footer. End the concept material with a callout linking to the architecture companion (see RECIPE-GUIDE.md for the exact callout text and the architecture-companion structure).
2. chapter11.10-architecture.md gets: all AWS-specific implementation content (why these services, architecture diagram, prerequisites, ingredients, pseudocode walkthrough, expected results), why-this-isn't-production-ready, variations, additional resources, and estimated implementation time, with a backlink header to the main recipe and a footer linking to the main recipe and the Python example.
Remove any leftover review scaffolding (for example an 'Open Code Review Findings' section). Preserve all real content. No em dashes.
