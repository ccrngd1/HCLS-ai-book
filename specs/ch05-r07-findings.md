---
id: ch05-r07-findings
title: 'Resolve open findings: Recipe 5.7: Longitudinal Patient Matching Across Name Changes ⭐⭐⭐⭐'
target_persona: TechWriter
tags:
- chapter05
- recipe
- finding-resolution
depends_on: []
validation:
- type: file_exists
  name: recipe-files-exist
  paths:
  - chapter05.07-architecture.md
  - chapter05.07-longitudinal-patient-matching-name-changes.md
  - chapter05.07-python-example.md
- type: shell
  name: findings-guardrail
  commands:
  - python3 check_findings.py chapter05.07
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: >-
    Every open finding listed in chapter05.07-todo.md has been either (a) resolved
    in the correct source file with a technically sound, HIPAA-compliant,
    architecture-correct fix, or (b) explicitly deferred with a one-line
    '[NEEDS HUMAN]' note in the todo file and a reason. The architecture
    companion and the python example remain mutually consistent. No clinical or
    security regressions. Resolved items removed from chapter05.07-todo.md. No new em dashes are introduced into the recipe source files.
---


## Objective
Resolve the open expert-review and code-review findings for Recipe 5.7: Longitudinal Patient Matching Across Name Changes ⭐⭐⭐⭐, listed in `chapter05.07-todo.md`.

## Inputs
- `chapter05.07-todo.md` (the open findings checklist).
- Reviewer context: `reviews/chapter05.07-expert-review.md`, `reviews/chapter05.07-code-review.md`.
- Recipe source files:
  - `chapter05.07-architecture.md`
  - `chapter05.07-longitudinal-patient-matching-name-changes.md`
  - `chapter05.07-python-example.md`

## Instructions
1. Read `chapter05.07-todo.md` (and any review files above) for full context on each finding.
2. Apply each finding's specified fix to the appropriate source file. Most land in the architecture companion or the python example; edit the main/story file only if a finding truly concerns it.
3. Keep the architecture companion and python example mutually consistent.
4. Remove each resolved entry from `chapter05.07-todo.md`.
5. If a finding needs an external citation you cannot verify, or a product decision only the author can make, leave it in `chapter05.07-todo.md` prefixed with `[NEEDS HUMAN]` and a one-line reason. Do not guess.
6. Do not reintroduce `<!-- TODO -->` comments into the source files.
7. No em dashes. Match the existing voice and RECIPE-GUIDE structure.

## Notes
Correctness over completeness: a subtly wrong HIPAA/architecture fix is worse than an honest `[NEEDS HUMAN]` deferral. The expert reviewer validating this task raised these findings; fixes must actually satisfy them.
