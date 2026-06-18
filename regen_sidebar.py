#!/usr/bin/env python3
"""Single-pass _Sidebar.md regenerator: insert -architecture nav entries.

For every chapterNN.RR-architecture.md on disk, ensure the sidebar has an
"Architecture and Implementation" entry nested under that recipe, placed
between the main recipe entry and its Python Example entry. Idempotent:
re-running makes no change once entries are present.

Anchoring strategy (per recipe prefix), in order of preference:
  1. Insert immediately BEFORE the recipe's Python Example line.
  2. Else insert immediately AFTER the recipe's main entry line.

Preserves the file's existing line endings (CRLF in this repo).

Usage: python3 regen_sidebar.py [--apply]
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

SIDEBAR = "_Sidebar.md"


def main() -> int:
    apply = "--apply" in sys.argv
    raw = Path(SIDEBAR).read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(nl)

    # All recipe prefixes that have an architecture companion on disk.
    prefixes = sorted(
        re.match(r"(chapter\d+\.\d+)-architecture\.md", Path(f).name).group(1)
        for f in glob.glob("chapter*.*-architecture.md")
    )

    inserted = 0
    for prefix in prefixes:
        arch_target = f"{prefix}-architecture"
        # Already present?
        if any(f"({arch_target})" in ln for ln in lines):
            continue
        arch_line = f"  * [Architecture and Implementation]({arch_target})"

        py_idx = next(
            (i for i, ln in enumerate(lines) if f"({prefix}-python-example)" in ln),
            None,
        )
        if py_idx is not None:
            lines.insert(py_idx, arch_line)
            inserted += 1
            continue

        main_idx = next(
            (i for i, ln in enumerate(lines)
             if re.search(rf"\({prefix}-(?!architecture|python-example)[^)]+\)", ln)),
            None,
        )
        if main_idx is not None:
            lines.insert(main_idx + 1, arch_line)
            inserted += 1
        else:
            print(f"  WARN: no sidebar anchor found for {prefix}")

    print(f"  architecture companions on disk: {len(prefixes)}")
    print(f"  {'inserted' if apply else 'would insert'} {inserted} nav entries")

    if apply and inserted:
        Path(SIDEBAR).write_text(nl.join(lines), encoding="utf-8")
        print(f"  WROTE {SIDEBAR}")
    elif not apply:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
