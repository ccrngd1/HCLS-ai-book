#!/usr/bin/env python3
"""Remove or restore the Honest Take section in non-flagship recipes.

The 15 flagship recipes ship in the print edition and keep their Honest Take. The
other 137 are digital-only, and their Honest Take sections are being withheld for
now.

This is reversible by design. Each removed section is written verbatim to
honest-takes-stash/, so --restore puts it back exactly, and the stash is tracked in
git rather than relying on history archaeology across 137 files.

Structure is uniform across all 137: "## The Honest Take" is always followed by
"## Related Recipes", so the boundary is unambiguous.

    python3 honest_takes.py             # dry run, shows what would change
    python3 honest_takes.py --remove
    python3 honest_takes.py --restore

Not touched: companion pages (architecture, Python) that mention the Honest Take in
passing. Roughly 100 of those are a stock footer listing what the main recipe
contains, and about a dozen are in-body references. Rewriting them for a temporary
change and then reverting would be more churn and more risk than leaving them.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

STASH = Path("honest-takes-stash")
HEADING = "## The Honest Take"
NEXT = "## Related Recipes"


def flagship() -> set[str]:
    man = json.loads(Path("print/manifest.json").read_text(encoding="utf-8"))
    return {e["recipe"] for e in man["flagship"]}


def recipe_id(name: str) -> str | None:
    m = re.match(r"chapter(\d+)\.(\d+)-", name)
    return f"{int(m.group(1))}.{int(m.group(2))}" if m else None


def non_flagship_mains() -> list[Path]:
    flag = flagship()
    out = []
    for f in sorted(glob.glob("chapter*.md")):
        if not re.match(r"chapter\d+\.\d+-", f):
            continue
        if re.search(r"-(todo|architecture|python-example)\.md$", f):
            continue
        if recipe_id(f) in flag:
            continue
        out.append(Path(f))
    return out


def split_section(text: str) -> tuple[str, str, str] | None:
    """Return (before, section, after) around the Honest Take, or None."""
    m = re.search(rf"^{re.escape(HEADING)}\s*$", text, re.M)
    if not m:
        return None
    n = re.search(rf"^{re.escape(NEXT)}\s*$", text[m.start():], re.M)
    if not n:
        return None
    end = m.start() + n.start()
    return text[: m.start()], text[m.start(): end], text[end:]


def do_remove(apply: bool) -> int:
    STASH.mkdir(exist_ok=True)
    n = words = 0
    for path in non_flagship_mains():
        text = path.read_text(encoding="utf-8")
        parts = split_section(text)
        if parts is None:
            continue
        before, section, after = parts
        rid = recipe_id(path.name)
        n += 1
        words += len(section.split())
        if apply:
            (STASH / f"{path.stem}.md").write_text(
                f"<!-- Removed from {path.name} by honest_takes.py. "
                f"Restore with: python3 honest_takes.py --restore -->\n\n" + section,
                encoding="utf-8",
            )
            path.write_text(before.rstrip("\n") + "\n\n" + after, encoding="utf-8")
        else:
            print(f"  would remove {len(section.split()):5d} words from {path.name}")
    verb = "removed" if apply else "would remove"
    print(f"\n  sections {verb}: {n}   words: {words:,}")
    if apply:
        print(f"  stashed in {STASH}/ ({n} files)")
    return 0


def do_restore(apply: bool, only: list[str] | None = None) -> int:
    """Restore stashed sections. ``only`` accepts recipe ids like 7.3 or 07.03."""
    if not STASH.is_dir():
        print(f"  no {STASH}/ directory; nothing to restore")
        return 1
    wanted = None
    if only:
        wanted = {f"{int(a)}.{int(b)}" for a, b in
                  (s.split(".") for s in (x.replace("chapter", "") for x in only))}
    n = 0
    for stash_file in sorted(STASH.glob("*.md")):
        if wanted is not None and recipe_id(stash_file.name) not in wanted:
            continue
        target = Path(f"{stash_file.stem}.md")
        if not target.exists():
            print(f"  SKIP: {target} not found")
            continue
        text = target.read_text(encoding="utf-8")
        if HEADING in text:
            continue  # already restored
        section = re.sub(r"^<!--.*?-->\s*", "", stash_file.read_text(encoding="utf-8"), flags=re.S)
        if NEXT not in text:
            print(f"  SKIP: {target} has no {NEXT!r} to anchor against")
            continue
        i = text.index(NEXT)
        n += 1
        if apply:
            target.write_text(text[:i] + section.rstrip("\n") + "\n\n" + text[i:], encoding="utf-8")
            stash_file.unlink()  # so --status reflects real progress
        else:
            print(f"  would restore into {target.name}")
    verb = "restored" if apply else "would restore"
    print(f"\n  sections {verb}: {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--remove", action="store_true")
    g.add_argument("--restore", action="store_true")
    ap.add_argument(
        "recipes", nargs="*",
        help="with --restore, limit to these recipe ids (e.g. 7.3 12.05); default is all",
    )
    ap.add_argument("--status", action="store_true", help="show how many are withheld")
    args = ap.parse_args()
    if args.status:
        total = len(non_flagship_mains())
        withheld = len(list(STASH.glob("*.md"))) if STASH.is_dir() else 0
        print(f"  non-flagship recipes: {total}")
        print(f"  Honest Take withheld: {withheld}")
        print(f"  restored so far:      {total - withheld}")
        return 0
    if args.restore:
        return do_restore(True, args.recipes or None)
    if args.remove:
        return do_remove(True)
    print("  DRY RUN (pass --remove or --restore)\n")
    return do_remove(False)


if __name__ == "__main__":
    sys.exit(main())
