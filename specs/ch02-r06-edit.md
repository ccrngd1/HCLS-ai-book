---
id: ch02-r06-edit
title: 'Final Edit: Clinical Note Summarization'
target_persona: TechEditor
tags:
- chapter02
- recipe
- edit
depends_on:
- ch02-r06-code-review
- ch02-r06-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter02.06-clinical-note-summarization.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter02.06-clinical-note-summarization.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Clinical Note Summarization.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
