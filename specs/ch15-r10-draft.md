---
id: ch15-r10-draft
title: 'Draft: Hospital Resource Allocation Under Uncertainty'
target_persona: TechWriter
tags:
- chapter15
- recipe
- draft
depends_on:
- ch15-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter15.10-hospital-resource-allocation-uncertainty.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter15.10-hospital-resource-allocation-uncertainty.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Hospital Resource Allocation Under Uncertainty using reinforcement learning.

## Instructions
Write a complete recipe covering architecture patterns, implementation approach, hidden challenges, and limitations for Hospital Resource Allocation Under Uncertainty. Follow the cookbook format with problem statement, solution architecture, and production considerations. Include state/action/reward formulation, safety constraints, and offline vs online learning tradeoffs.
