---
id: ch04-r07-edit
title: 'Final Edit: Care Management Program Enrollment'
target_persona: TechEditor
tags:
- chapter04
- recipe
- edit
depends_on:
- ch04-r07-code-review
- ch04-r07-expert-review
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter04.07-care-management-program-enrollment.md
- type: shell
  name: auto-fix-style
  commands:
  - python fix_style.py chapter04.07-care-management-program-enrollment.md
- type: persona_review
  name: quality-review
  persona: TechExpertReviewer
  pass_condition: No style guide violations, no em dashes, correct header hierarchy,
    all code blocks have language tags, voice consistent with STYLE-GUIDE.md. HIGH/MEDIUM
    technical findings from reviews are either incorporated or explicitly flagged
    as TODO markers for the TechWriter.
---


## Objective
Produce the final edited version of Care Management Program Enrollment.

## Instructions
Incorporate feedback from code review and expert review. Ensure consistency with book style, fix any technical or clinical inaccuracies, and finalize the recipe.
