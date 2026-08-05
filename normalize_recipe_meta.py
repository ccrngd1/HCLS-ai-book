#!/usr/bin/env python3
"""Normalize recipe front-matter: one Effort rating, no Phase, no Cost, no emoji.

Why:
  * **Phase** carried 41 distinct values across 152 recipes, including freeform
    sentences and at least one entry that was not a phase at all. It could not be
    used to compare recipes, so it was noise wearing a label.
  * **Estimated Cost** mixed non-comparable units (per-card, per-note, per-query,
    per-month) and depended on model pricing that moves quarterly. In a printed
    book it can only rot.
  * **Complexity** and effort are the same idea, so they collapse into a single
    "Effort" rating on a documented 1-5 scale.
  * Title **emoji** are removed. They are decorative, the legacy star ratings were
    undocumented and applied to only 58 of 152 recipes, and none of the embedded
    print fonts contain the glyphs, so they could never render in the PDF.

Effort is rendered as text ("4 of 5") rather than star characters on purpose:
Gelasio, the embedded body face, has no star, circle, or geometric-shape glyph, so
any symbol form would tofu in print or silently fall back to a monospace font.

Mapping from the retired Complexity values:
    Simple          -> 1
    Simple-Medium   -> 2
    Medium/Moderate -> 3
    Medium-Complex  -> 4
    Complex         -> 5

Idempotent. Usage:
  python3 normalize_recipe_meta.py            # dry run
  python3 normalize_recipe_meta.py --apply
"""
from __future__ import annotations

import glob
import re
import sys
from collections import Counter
from pathlib import Path

COMPLEXITY_TO_EFFORT = {
    "simple": 1,
    "simple-medium": 2,
    "medium": 3,
    "moderate": 3,
    "medium-complex": 4,
    "complex": 5,
}

# Emoji observed in headings: star, orange/blue diamonds, hospital, plus VS16.
EMOJI_RE = re.compile(
    "[\u2b50\U0001F536\U0001F537\U0001F3E5\uFE0F\u2605\u2606]"
)

COMPANION_SUFFIXES = ("-architecture.md", "-python-example.md", "-todo.md")


def is_main(path: str) -> bool:
    name = Path(path).name
    if not re.match(r"chapter\d+\.\d+-", name):
        return False
    return not name.endswith(COMPANION_SUFFIXES)


def clean_heading(line: str) -> str:
    out = EMOJI_RE.sub("", line)
    # collapse whitespace left behind, preserve the leading hashes
    out = re.sub(r"[ \t]{2,}", " ", out).rstrip()
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    all_md = sorted(glob.glob("chapter*.md"))
    stats = Counter()
    effort_dist = Counter()
    unmapped = []

    for path in all_md:
        name = Path(path).name
        if name.endswith("-todo.md"):
            continue
        p = Path(path)
        text = original = p.read_text(encoding="utf-8")
        lines = text.split("\n")

        # 1. Strip emoji from the H1 (and any other heading that carries one).
        for i, ln in enumerate(lines):
            if ln.startswith("#") and EMOJI_RE.search(ln):
                lines[i] = clean_heading(ln)
                stats["headings_cleaned"] += 1

        # 2. Replace the metadata line on main recipe files.
        if is_main(path):
            for i, ln in enumerate(lines):
                if not ln.startswith("**Complexity:**"):
                    continue
                m = re.match(r"\*\*Complexity:\*\*\s*([^·\n]+)", ln)
                raw = (m.group(1).strip() if m else "").lower()
                effort = COMPLEXITY_TO_EFFORT.get(raw)
                if effort is None:
                    unmapped.append((name, raw))
                    stats["unmapped"] += 1
                    break
                lines[i] = f"**Effort:** {effort} of 5"
                effort_dist[effort] += 1
                stats["meta_rewritten"] += 1
                break
            else:
                if "**Effort:**" not in text:
                    stats["main_missing_meta"] += 1

        new = "\n".join(lines)
        if new != original:
            stats["files_changed"] += 1
            if apply:
                p.write_text(new, encoding="utf-8")

    print("  " + ("APPLIED" if apply else "DRY RUN"))
    for k in ("files_changed", "headings_cleaned", "meta_rewritten",
              "unmapped", "main_missing_meta"):
        if stats[k]:
            print(f"    {k:22s} {stats[k]}")
    if effort_dist:
        print("    effort distribution:")
        total = sum(effort_dist.values())
        for lvl in sorted(effort_dist):
            n = effort_dist[lvl]
            print(f"      {lvl} of 5: {n:3d}  ({100*n/total:4.1f}%)  {'#'*n}")
    for name, raw in unmapped[:10]:
        print(f"    UNMAPPED complexity {raw!r} in {name}")
    if not apply:
        print("  (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
