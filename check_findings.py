#!/usr/bin/env python3
"""Guardrail check for recipe finding-resolution tasks.

Usage: python3 check_findings.py chapterNN.RR

Light structural guard (the substantive gate is the TechExpertReviewer
persona_review). Verifies:
  1. The recipe's source files exist.
  2. No inline '<!-- TODO ... -->' comments were (re)introduced into the
     source files outside code fences (findings are tracked in the -todo.md
     file, not littered back into the prose/code).
  3. The -todo.md tracking file still exists.
Exit 0 = pass, non-zero = fail.
"""
import sys, re, glob, os

def main(prefix: str) -> int:
    srcs = [f for f in glob.glob(f"{prefix}-*.md") if not f.endswith("-todo.md")]
    if not srcs:
        print(f"FAIL: no source files for {prefix}")
        return 1
    reintroduced = []
    for f in srcs:
        infence = False
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if line.lstrip().startswith("```"):
                infence = not infence
                continue
            if not infence and re.search(r"<!--\s*TODO", line, re.I):
                reintroduced.append(f"{f}:{i}")
    if reintroduced:
        print("FAIL: inline TODO comments reintroduced into source:",
              ", ".join(reintroduced[:5]))
        return 1
    todo = f"{prefix}-todo.md"
    if not os.path.exists(todo):
        print(f"FAIL: {todo} missing (must remain as the tracking record)")
        return 1
    open_items = sum(1 for l in open(todo, encoding="utf-8") if l.startswith("- **L"))
    print(f"OK: {prefix} sources present ({len(srcs)}), no reintroduced inline "
          f"TODOs, {todo} present ({open_items} open items remaining)")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 check_findings.py chapterNN.RR")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
