#!/usr/bin/env python3
"""Validate that a recipe was split correctly into main + architecture.

Checks, given a recipe prefix (e.g. chapter03.01) or a main filename:
  1. Both the main file and the -architecture file exist.
  2. The AWS Part-2 boundary (## The AWS Implementation / Why These Services)
     is ABSENT from the main file and PRESENT in the architecture file.
  3. The main file contains the callout link to the architecture companion.
  4. The architecture file contains a backlink to the main recipe.
  5. The Honest Take is on the main file (not the architecture file).

Exit 0 if all pass, 1 otherwise. Designed as a ralph `shell` validation check.

Usage: python3 check_split.py <chapterNN.RR | main-file.md>
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path


def resolve(arg: str):
    """Return (main_path, arch_path) from a prefix or a main filename."""
    if arg.endswith(".md"):
        main = Path(arg)
        prefix = re.match(r"(chapter\d+\.\d+)", main.name).group(1)
    else:
        prefix = arg
        matches = [
            f for f in glob.glob(f"{prefix}-*.md")
            if "-architecture" not in f and "-python-example" not in f
        ]
        if not matches:
            print(f"  FAIL: no main file found for prefix {prefix}")
            sys.exit(1)
        main = Path(matches[0])
    arch = Path(f"{prefix}-architecture.md")
    return main, arch


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 check_split.py <chapterNN.RR | main-file.md>")
        return 1
    main_path, arch_path = resolve(sys.argv[1])
    errors = []

    if not main_path.is_file():
        errors.append(f"main file missing: {main_path}")
        print("\n".join(f"  FAIL: {e}" for e in errors))
        return 1
    if not arch_path.is_file():
        errors.append(f"architecture file missing: {arch_path}")
        print("\n".join(f"  FAIL: {e}" for e in errors))
        return 1

    main_text = main_path.read_text(encoding="utf-8")
    arch_text = arch_path.read_text(encoding="utf-8")

    boundary = re.compile(r"^##+ .*(Why These Services|AWS Implementation)\b", re.MULTILINE)
    if boundary.search(main_text):
        errors.append("AWS boundary still present in main file")
    if not boundary.search(arch_text):
        errors.append("AWS boundary missing from architecture file")

    arch_stem = arch_path.stem  # chapterNN.RR-architecture
    if arch_stem not in main_text:
        errors.append("main file missing callout link to architecture companion")
    if main_path.stem not in arch_text:
        errors.append("architecture file missing backlink to main recipe")

    if "## The Honest Take" not in main_text:
        errors.append("Honest Take missing from main file")
    if "## The Honest Take" in arch_text:
        errors.append("Honest Take leaked into architecture file")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    print(f"  OK: {main_path.name} + {arch_path.name} split is structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
