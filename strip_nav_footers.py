#!/usr/bin/env python3
"""Remove hand-written navigation footers from recipe sources.

The digital edition now generates previous/next navigation from ``_Sidebar.md``
at render time, so a footer stored in the source can only ever drift from it.
Historically these were written by hand in four different shapes, which is why
they were missing on some pages and malformed on others (one shape emits a
table separator row *after* its content row, so it renders as literal text).

Idempotent. Dry run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

ARROW = "\u2190"  # left arrow: every footer shape contains one
FOOTER_RE = re.compile(r"\]\(chapter[^)]*\)")
TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


def _in_code_fence(lines: list[str], index: int) -> bool:
    """True if ``index`` sits inside a fenced code block."""
    fences = 0
    for line in lines[:index]:
        if line.lstrip().startswith("```"):
            fences += 1
    return fences % 2 == 1


def _footer_span(lines: list[str]) -> tuple[int, int] | None:
    """Return the [start, end) span of the nav footer block, if any.

    Handles both orderings found in the corpus: the footer as the last thing in
    the file, and the footer sitting above a trailing ``## Tags`` section. Only
    lines that actually contain a nav link are removed, plus the table separator
    some shapes emit and the horizontal rule that introduced the block.
    """
    hits = [
        i
        for i, line in enumerate(lines)
        if ARROW in line and FOOTER_RE.search(line) and not _in_code_fence(lines, i)
    ]
    if not hits:
        return None
    start = end = hits[-1]
    while end + 1 < len(lines) and (
        TABLE_SEP_RE.match(lines[end + 1].strip())
        or (ARROW in lines[end + 1] and FOOTER_RE.search(lines[end + 1]))
    ):
        end += 1
    end += 1
    # Walk back over the blanks and the horizontal rule that set the block off.
    while start > 0 and lines[start - 1].strip() == "":
        start -= 1
    if start > 0 and lines[start - 1].strip() == "---":
        start -= 1
        while start > 0 and lines[start - 1].strip() == "":
            start -= 1
    # If content follows, leave a single blank line so the next block is spaced.
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    return start, end


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()

    # Python companions are deliberately absent from _Sidebar.md, so the
    # generator emits nothing for them. Stripping their footer would leave those
    # pages with no way back to the recipe, so they keep the hand-written one.
    files = [
        f
        for f in sorted(glob.glob("chapter*.md"))
        if not f.endswith(("-todo.md", "-python-example.md"))
    ]
    changed = 0
    removed_lines = 0
    for name in files:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        span = _footer_span(lines)
        if span is None:
            continue
        start, end = span
        head = lines[:start]
        tail = lines[end:]
        while head and head[-1].strip() == "":
            head.pop()
        if tail:
            # Content followed the footer (a trailing Tags section), so restore
            # the horizontal rule that separated it from the body.
            kept = head + ["", "---", ""] + tail
        else:
            kept = head
        changed += 1
        removed_lines += end - start
        if args.apply:
            path.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
        else:
            print(f"  {name}: would remove lines {start + 1}-{end}")
            for line in lines[start:end]:
                print(f"      - {line[:96]}")

    verb = "removed" if args.apply else "would remove"
    print(f"\n  files with a trailing nav footer: {changed}")
    print(f"  lines {verb}: {removed_lines}")
    if not args.apply:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
