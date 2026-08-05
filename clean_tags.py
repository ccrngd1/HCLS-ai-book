#!/usr/bin/env python3
"""Remove retired Complexity and Phase values from recipe Tags sections.

The Complexity and Phase header fields were retired in 2026-08 (Phase had drifted
to 41 non-comparable values; Complexity folded into Effort). Their values had also
been mirrored into the Tags list, so the tags now contradict the header: a recipe
whose header says "Effort: 3 of 5" still carried tags like `complex` and `mvp`.

Removes the mirrored values only. Does NOT remove `regulated`, which originated as
a Phase value but reads as a genuine descriptor of regulatory exposure and
duplicates no current header field.

No new tags are added.

Idempotent. Usage:
  python3 clean_tags.py            # dry run
  python3 clean_tags.py --apply
"""
from __future__ import annotations

import glob
import re
import sys
from collections import Counter
from pathlib import Path

RETIRED = {
    # retired Complexity vocabulary
    "simple", "medium", "complex", "moderate", "medium-complex", "simple-medium",
    # retired Phase vocabulary
    "mvp", "mvp-plus", "production", "production-track",
    "phase-1-2", "phase-2", "phase-3",
    "research-pilot", "research-to-production", "research-production",
    "research-production-hybrid", "quick-win", "pilot",
    "foundation", "foundational", "strategic-planning",
}

TAGS_BLOCK = re.compile(r"(^## Tags\s*\n)(.+?)(?=\n##|\n---|\Z)", re.S | re.M)


def main() -> int:
    apply = "--apply" in sys.argv
    mains = [
        f for f in sorted(glob.glob("chapter*.md"))
        if not re.search(
            r"-(todo|architecture|python-example|preface|index|executive-summary)\.md$", f
        )
    ]

    removed = Counter()
    files_changed = 0
    multiline = 0

    for path in mains:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        m = TAGS_BLOCK.search(text)
        if not m:
            continue
        head, block = m.group(1), m.group(2)
        tags = re.findall(r"`([^`]+)`", block)
        if not tags:
            continue
        if block.strip().count("\n"):
            multiline += 1

        kept = [t for t in tags if t.lower() not in RETIRED]
        gone = [t for t in tags if t.lower() in RETIRED]
        if not gone:
            continue
        removed.update(t.lower() for t in gone)

        trailing = "\n" if block.endswith("\n") else ""
        new_block = " · ".join(f"`{t}`" for t in kept) + trailing
        new_text = text[: m.start()] + head + new_block + text[m.end():]
        files_changed += 1
        if apply:
            p.write_text(new_text, encoding="utf-8")

    print("  " + ("APPLIED" if apply else "DRY RUN"))
    print(f"    recipes scanned:      {len(mains)}")
    print(f"    recipes changed:      {files_changed}")
    print(f"    multi-line Tags:      {multiline} (reflowed to one line)")
    print(f"    tag removals:         {sum(removed.values())}")
    for t, n in removed.most_common():
        print(f"      {n:4d}  {t}")
    if not apply:
        print("  (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
