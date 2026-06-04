#!/usr/bin/env python3
"""Auto-fix trivial style violations: em dashes and bare code blocks.

Usage: python fix_style.py <file> [<file> ...]

Exits 0 always (fixes are applied in-place). Designed to run as a shell
validation check BEFORE persona_review so the reviewer sees clean content.
"""
import re
import sys
from pathlib import Path


def fix_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text

    # Replace em dashes with colon-space or comma-space depending on context
    text = text.replace("\u2014", ": ")  # em dash
    text = text.replace("\u2013", "-")   # en dash -> hyphen

    # Fix double-space artifacts from em dash replacement
    text = re.sub(r":  +", ": ", text)

    # Tag bare *opening* code fences only. A bare ``` is ambiguous on its
    # own, so we track open/close state line by line: the first bare ```
    # opens a block (tag it `text`), the matching ``` closes it (leave
    # bare). This never touches closing fences, which must stay bare, and
    # never re-tags fences that already carry a language.
    lines = text.split("\n")
    in_block = False
    for i, line in enumerate(lines):
        if re.match(r"^```", line.rstrip()):
            if not in_block:
                in_block = True
                if line.rstrip() == "```":  # bare opening fence
                    lines[i] = "```text"
            else:
                in_block = False  # closing fence: leave exactly as-is
    text = "\n".join(lines)

    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"fixed: {path}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.exists():
            fix_file(p)
