#!/usr/bin/env python3
"""Re-apply the tag vocabulary from the pre-vocabulary state, with no cap.

Why this exists rather than re-running apply_tag_vocabulary.py: the capped run
already overwrote each recipe's Tags section, so the discarded tags are no longer
in the working tree. They have to be recovered from git and re-mapped.

Source of truth for the original tags is the commit before the vocabulary landed.
Recipes whose Tags section was created by that same commit (the ten that had none)
are left as they are, since git has nothing earlier to recover.

Usage:
  python3 reapply_tags_uncapped.py <base-ref>            # dry run
  python3 reapply_tags_uncapped.py <base-ref> --apply
"""
from __future__ import annotations

import glob
import json
import re
import subprocess
import sys
from pathlib import Path

TAGS_BLOCK = re.compile(r"(^## Tags\s*\n)(.+?)(?=\n##|\n---|\Z)", re.S | re.M)


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-P", "show", f"{ref}:./{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: reapply_tags_uncapped.py <base-ref> [--apply]")
        return 2
    base = args[0]
    apply = "--apply" in sys.argv

    v = json.load(open("tag-vocabulary.json", encoding="utf-8"))
    order, canon, facet_of = [], set(), {}
    for facet, ts in v["facets"].items():
        for t in ts:
            if t not in canon:
                order.append(t); canon.add(t); facet_of[t] = facet
    alias = {k.strip(): val.strip() for k, val in v["aliases"].items()}
    rank = {t: i for i, t in enumerate(order)}

    mains = [
        f for f in sorted(glob.glob("chapter*.md"))
        if not re.search(
            r"-(todo|architecture|python-example|preface|index|executive-summary)\.md$", f)
    ]

    changed = kept_current = 0
    before = after = 0
    biggest = []

    for path in mains:
        old = git_show(base, path)
        if old is None:
            kept_current += 1
            continue
        om = TAGS_BLOCK.search(old)
        if not om:
            kept_current += 1          # section created later; nothing to recover
            continue
        raw = [x.lower().strip() for x in re.findall(r"`([^`]+)`", om.group(2))]

        out = []
        for t in raw:
            c = t if t in canon else alias.get(t)
            if c and c not in out:
                out.append(c)
        out.sort(key=lambda t: rank.get(t, 10**6))

        p = Path(path)
        text = p.read_text(encoding="utf-8")
        cm = TAGS_BLOCK.search(text)
        if not cm:
            kept_current += 1
            continue
        cur = [x.lower() for x in re.findall(r"`([^`]+)`", cm.group(2))]
        before += len(cur); after += len(out)
        if len(out) != len(cur):
            changed += 1
            biggest.append((path, len(cur), len(out)))
        trailing = "\n" if cm.group(2).endswith("\n") else ""
        new_block = " · ".join(f"`{t}`" for t in out) + trailing
        if apply and new_block != cm.group(2):
            p.write_text(text[: cm.start()] + cm.group(1) + new_block + text[cm.end():],
                         encoding="utf-8")

    print("  " + ("APPLIED" if apply else "DRY RUN"))
    print(f"    base ref                 {base}")
    print(f"    recipes re-expanded      {changed}")
    print(f"    recipes left as-is       {kept_current}")
    print(f"    tag occurrences          {before} -> {after}  (+{after-before})")
    for path, a, b in sorted(biggest, key=lambda r: r[1] - r[2])[:6]:
        print(f"      {Path(path).name[:52]:54s} {a:3d} -> {b:3d}")
    if not apply:
        print("  (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
