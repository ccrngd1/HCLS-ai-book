#!/usr/bin/env python3
"""Check (and optionally fix) section-divider rules (`---`) in main recipes.

`---` is a thematic break: a thin rule in print, the EPUB and the site. It is
never a page break; page breaks come only from CSS at chapter starts. The
rules, also written up in RECIPE-GUIDE.md:

  1. Exactly one `---` after the header block (title, Effort line, User line),
     before any callout and before The Problem.
  2. Exactly one `---` directly above every `##` section except The Problem,
     which rule 1 already separates from the header.
  3. No `---` anywhere else: not above `###`, not inside a section, not around
     callouts, never two in a row, never at the end of the file.

Only lines outside fenced code and HTML comments are considered. A fix only
moves rule lines and the blank lines around them; it verifies that nothing
else in the file changed before writing.

  python3 check_rules.py            # report on the 15 print recipes
  python3 check_rules.py --all      # report on all 152 main recipes
  python3 check_rules.py --fix 3.1  # rewrite one recipe (or --fix for all in scope)
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULE = re.compile(r"^\s*-{3,}\s*$")


def main_recipe(recipe: str) -> str | None:
    ch, rr = recipe.split(".")
    for p in sorted(glob.glob(os.path.join(HERE, f"chapter{int(ch):02d}.{int(rr):02d}-*.md"))):
        if not p.endswith(("-architecture.md", "-python-example.md", "-todo.md")):
            return p
    return None


def scope(all_recipes: bool) -> list[str]:
    if all_recipes:
        return sorted(p for p in glob.glob(os.path.join(HERE, "chapter[0-9][0-9].[0-9][0-9]-*.md"))
                      if not p.endswith(("-architecture.md", "-python-example.md", "-todo.md")))
    man = json.load(open(os.path.join(HERE, "print", "manifest.json"), encoding="utf-8"))
    return [p for p in (main_recipe(e["recipe"]) for e in man["flagship"]) if p]


def prose_mask(lines: list[str]) -> list[bool]:
    """True for lines that are markdown prose (outside fences and HTML comments)."""
    mask, fence, comment = [], False, False
    for ln in lines:
        if not comment and ln.lstrip().startswith("```"):
            fence = not fence
            mask.append(False)
            continue
        if fence:
            mask.append(False)
            continue
        if not comment and "<!--" in ln and "-->" not in ln.split("<!--", 1)[1]:
            comment = True
            mask.append(False)
            continue
        if comment:
            if "-->" in ln:
                comment = False
            mask.append(False)
            continue
        mask.append(True)
    return mask


def expected(lines: list[str]) -> list[str]:
    """Return the file's lines with rules placed per the rules above."""
    mask = prose_mask(lines)
    first_h2 = next(i for i, ln in enumerate(lines) if mask[i] and ln.startswith("## "))
    # The header block ends at the first rule, callout, comment or heading after
    # the title and metadata; rule 1 goes there.
    header_end = next(i for i in range(1, len(lines))
                      if i == first_h2 or (mask[i] and RULE.match(lines[i]))
                      or lines[i].startswith((">", "<!--")))
    out: list[str] = []
    for i, ln in enumerate(lines):
        if i == header_end:
            out += ["---", ""]
        if mask[i] and RULE.match(ln):
            continue                                   # drop every rule; re-added above
        if mask[i] and ln.startswith("## ") and i != first_h2 and not ln.startswith("## The Problem"):
            out += ["---", ""]
        out.append(ln)
    # Collapse blank runs and blank-before-rule doubling the drop may have left.
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    text = re.sub(r"(?m)^(---\n\n)(?:---\n\n)+", r"\1", text)
    return text.rstrip("\n").split("\n")


def content_only(text: str) -> str:
    """The file with every rule and blank line removed, for the safety check."""
    lines = text.split("\n")
    mask = prose_mask(lines)
    return "\n".join(ln for i, ln in enumerate(lines)
                     if ln.strip() and not (mask[i] and RULE.match(ln)))


def check(path: str) -> list[str]:
    lines = open(path, encoding="utf-8").read().rstrip("\n").split("\n")
    want = expected(lines)
    if [l for l in lines if l.strip()] == [l for l in want if l.strip()]:
        return []
    mask = prose_mask(lines)
    have = [i + 1 for i, l in enumerate(lines) if mask[i] and RULE.match(l)]
    wmask = prose_mask(want)
    need_after = [want[j + 2][:50] for j, l in enumerate(want)
                  if wmask[j] and RULE.match(l) and j + 2 < len(want)]
    return [f"rules at lines {have}", "expected one before: " + " | ".join(need_after)]


def fix(path: str) -> bool:
    raw = open(path, encoding="utf-8").read()
    new = "\n".join(expected(raw.rstrip("\n").split("\n"))) + "\n"
    if new == raw:
        return False
    assert content_only(new) == content_only(raw), f"{path}: fix would change content"
    open(path, "w", encoding="utf-8").write(new)
    return True


if __name__ == "__main__":
    args = sys.argv[1:]
    paths = scope("--all" in args)
    targets = [a for a in args if re.fullmatch(r"\d+\.\d+", a)]
    if targets:
        paths = [main_recipe(t) for t in targets]
    if "--fix" in args:
        changed = [os.path.basename(p) for p in paths if fix(p)]
        print(f"fixed {len(changed)} file(s)" + (": " + ", ".join(changed) if changed else ""))
        sys.exit(0)
    bad = 0
    for p in paths:
        problems = check(p)
        if problems:
            bad += 1
            print(os.path.basename(p))
            for pr in problems:
                print("   ", pr)
    print(f"{len(paths) - bad} of {len(paths)} recipes follow the divider rules")
    sys.exit(1 if bad else 0)
