---
id: ch06-r02-findings
title: 'Resolve open findings: Recipe 6.2: Utilization Pattern Segmentation ⭐'
target_persona: TechWriter
tags:
- chapter06
- recipe
- finding-resolution
depends_on: []
validation:
- type: file_exists
  name: recipe-files-exist
  paths:
  - chapter06.02-architecture.md
  - chapter06.02-python-example.md
  - chapter06.02-utilization-pattern-segmentation.md
- type: shell
  name: findings-guardrail
  commands:
  - python3 check_findings.py chapter06.02
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: >-
    Every open finding listed in chapter06.02-todo.md has been either (a) resolved
    in the correct source file with a technically sound, HIPAA-compliant,
    architecture-correct fix, or (b) explicitly deferred with a one-line
    '[NEEDS HUMAN]' note in the todo file and a reason. The architecture
    companion and the python example remain mutually consistent. No clinical or
    security regressions. Resolved items removed from chapter06.02-todo.md. No em dashes.
---


## Objective
Resolve the open expert-review and code-review findings for Recipe 6.2: Utilization Pattern Segmentation ⭐, listed in `chapter06.02-todo.md`.

## Inputs
- `chapter06.02-todo.md` (the open findings checklist).
- Reviewer context: `reviews/chapter06.02-expert-review.md`, `reviews/chapter06.02-code-review.md`.
- Recipe source files:
  - `chapter06.02-architecture.md`
  - `chapter06.02-python-example.md`
  - `chapter06.02-utilization-pattern-segmentation.md`

## Instructions
1. Read `chapter06.02-todo.md` (and any review files above) for full context on each finding.
2. Apply each finding's specified fix to the appropriate source file. Most land in the architecture companion or the python example; edit the main/story file only if a finding truly concerns it.
3. Keep the architecture companion and python example mutually consistent.
4. Remove each resolved entry from `chapter06.02-todo.md`.
5. If a finding needs an external citation you cannot verify, or a product decision only the author can make, leave it in `chapter06.02-todo.md` prefixed with `[NEEDS HUMAN]` and a one-line reason. Do not guess.
6. Do not reintroduce `<!-- TODO -->` comments into the source files.
7. No em dashes. Match the existing voice and RECIPE-GUIDE structure.

## Notes
Correctness over completeness: a subtly wrong HIPAA/architecture fix is worse than an honest `[NEEDS HUMAN]` deferral. The expert reviewer validating this task raised these findings; fixes must actually satisfy them.
