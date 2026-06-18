#!/usr/bin/env python3
"""Generate finding-resolution tasks for every recipe with open findings.

Creates specs/chNN-rRR-findings.md + registers a task per recipe whose
chapterNN.RR-todo.md still has open items. Idempotent (skips existing tasks).
Does NOT launch ralph. After running this, launch with:

  rm -rf /tmp/ralph-worktrees; git worktree prune; \
  git branch | grep ralph/worker | xargs -r git branch -D
  <ralph> run --model claude-opus-4.6 --wall-clock-timeout-ms 57600000 --max-iterations 500

Run from the book root.
"""
import glob, re, json, os
from pathlib import Path

SPEC = """---
id: {tid}
title: 'Resolve open findings: {name}'
target_persona: TechWriter
tags:
- chapter{chap}
- recipe
- finding-resolution
depends_on: []
validation:
- type: file_exists
  name: recipe-files-exist
  paths:
{paths_yaml}
- type: shell
  name: findings-guardrail
  commands:
  - python3 check_findings.py {prefix}
- type: persona_review
  name: findings-resolved
  persona: TechExpertReviewer
  pass_condition: >-
    Every open finding listed in {prefix}-todo.md has been either (a) resolved
    in the correct source file with a technically sound, HIPAA-compliant,
    architecture-correct fix, or (b) explicitly deferred with a one-line
    '[NEEDS HUMAN]' note in the todo file and a reason. The architecture
    companion and the python example remain mutually consistent. No clinical or
    security regressions. Resolved items removed from {prefix}-todo.md. No em dashes.
---


## Objective
Resolve the open expert-review and code-review findings for {name}, listed in `{prefix}-todo.md`.

## Inputs
- `{prefix}-todo.md` (the open findings checklist).
{reviews_line}- Recipe source files:
{paths_bullets}

## Instructions
1. Read `{prefix}-todo.md` (and any review files above) for full context on each finding.
2. Apply each finding's specified fix to the appropriate source file. Most land in the architecture companion or the python example; edit the main/story file only if a finding truly concerns it.
3. Keep the architecture companion and python example mutually consistent.
4. Remove each resolved entry from `{prefix}-todo.md`.
5. If a finding needs an external citation you cannot verify, or a product decision only the author can make, leave it in `{prefix}-todo.md` prefixed with `[NEEDS HUMAN]` and a one-line reason. Do not guess.
6. Do not reintroduce `<!-- TODO -->` comments into the source files.
7. No em dashes. Match the existing voice and RECIPE-GUIDE structure.

## Notes
Correctness over completeness: a subtly wrong HIPAA/architecture fix is worse than an honest `[NEEDS HUMAN]` deferral. The expert reviewer validating this task raised these findings; fixes must actually satisfy them.
"""

def main():
    common = dict(retry_count=0, created_at_iteration=0, created_by_persona="Planner",
                  creation_chain=None, spilled_run_id="findings-batch",
                  admitted_run_id=None, resumed_from_interruption=None)
    tasks = json.load(open("tasks.json"))
    existing = {t["id"] for t in tasks}
    prio = 601
    added = 0
    todos = sorted(glob.glob("chapter*.*-todo.md"))
    for todo in todos:
        prefix = re.match(r"(chapter\d+\.\d+)", todo).group(1)
        chap = re.match(r"chapter(\d+)\.(\d+)", prefix).group(1)
        rr = re.match(r"chapter(\d+)\.(\d+)", prefix).group(2)
        tid = f"ch{chap}-r{rr}-findings"
        if tid in existing:
            continue
        open_items = sum(1 for l in open(todo, encoding="utf-8") if l.startswith("- **L"))
        if open_items == 0:
            continue
        srcs = [f for f in glob.glob(f"{prefix}-*.md") if not f.endswith("-todo.md")]
        if not srcs:
            continue
        main_f = next((f for f in srcs if "-architecture" not in f and "-python-example" not in f), srcs[0])
        m = re.search(r"^#\s+(.*)$", open(main_f, encoding="utf-8").read(), re.MULTILINE)
        name = (m.group(1).strip() if m else prefix).replace("'", "")
        paths_yaml = "\n".join(f"  - {f}" for f in sorted(srcs))
        paths_bullets = "\n".join(f"  - `{f}`" for f in sorted(srcs))
        reviews = [f for f in (f"reviews/{prefix}-expert-review.md", f"reviews/{prefix}-code-review.md") if os.path.exists(f)]
        reviews_line = ("- Reviewer context: " + ", ".join(f"`{r}`" for r in reviews) + ".\n") if reviews else ""
        Path(f"specs/{tid}.md").write_text(
            SPEC.format(tid=tid, name=name, chap=chap, prefix=prefix,
                        paths_yaml=paths_yaml, paths_bullets=paths_bullets,
                        reviews_line=reviews_line), encoding="utf-8")
        tasks.append({"id": tid, "title": f"Resolve open findings: {name}",
                      "priority": prio, "status": "pending", "spec_path": f"specs/{tid}.md",
                      "target_persona": "TechWriter", "depends_on": [],
                      "tags": [f"chapter{chap}", "recipe", "finding-resolution"], **common})
        prio += 1; added += 1; existing.add(tid)
    json.dump(tasks, open("tasks.json", "w"), indent=2)
    print(f"generated {added} finding-resolution tasks; tasks.json now {len(tasks)} total")

if __name__ == "__main__":
    main()
