---
id: ch04-r03-edit
title: 'Final Edit: Provider Directory Search Optimization'
target_persona: TechEditor
tags:
- chapter04
- recipe
- edit
depends_on:
- ch04-r03-code-review
- ch04-r03-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.03-provider-directory-search-optimization.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter04.03-provider-directory-search-optimization.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Provider Directory Search Optimization.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
