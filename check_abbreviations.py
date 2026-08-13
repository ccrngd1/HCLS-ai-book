#!/usr/bin/env python3
"""Check that abbreviations are spelled out on first use (R-1).

Deterministic gate for the R-1 ralph pass, so 152 tasks are verified by a script rather
than only by a persona reading prose. Exits non-zero on any violation.

    python3 check_abbreviations.py chapter07.03          # a recipe: main + architecture
    python3 check_abbreviations.py --all                 # whole corpus
    python3 check_abbreviations.py --report              # ranked worst-first, no failure

Rules enforced:
  * First PROSE use of an in-scope abbreviation on a page must carry its expansion.
  * Later uses on the same page must stay bare, so the pass cannot bloat the text by
    expanding every occurrence.
  * Code fences, inline code, link targets, and HTML comments are never prose.
  * Scope is per page, not per book: the architecture companion is a page a reader can
    land on directly, so it needs its own first-use expansion.
  * Python companions are out of scope. They are illustrative sketches kept out of the
    site navigation, and they are mostly code, where an abbreviation is an identifier.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

DATA = Path("abbreviations.json")


def load_terms() -> dict[str, str]:
    """Return {abbreviation: required first-use form} for in-scope terms only."""
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    terms: dict[str, str] = {}
    for group, body in raw.items():
        if group.startswith("_") or not isinstance(body, dict):
            continue
        for key, val in body.items():
            if key.startswith("_") or key == "terms" or not isinstance(val, dict):
                continue
            if val.get("expand"):
                terms[key] = val["form"]
    return terms


def prose_of(text: str) -> str:
    """Blank out everything that is not prose, preserving offsets so indices stay valid."""
    def blank(m: re.Match) -> str:
        return re.sub(r"\S", " ", m.group(0))

    text = re.sub(r"```.*?```", blank, text, flags=re.S)   # fenced code
    text = re.sub(r"~~~.*?~~~", blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", blank, text)               # inline code
    text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)  # comments
    text = re.sub(r"\]\([^)]*\)", blank, text)             # link targets
    text = re.sub(r"^\s{4,}\S.*$", blank, text, flags=re.M)  # indented code blocks
    return text


def pages_for(recipe: str) -> list[Path]:
    """Main recipe and architecture companion for a recipe id like chapter07.03."""
    out = []
    for p in sorted(glob.glob(f"{recipe}-*.md")):
        if p.endswith(("-todo.md", "-python-example.md")):
            continue
        out.append(Path(p))
    return out


def check_page(path: Path, terms: dict[str, str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    prose = prose_of(text)
    problems: list[str] = []

    for abbr, form in terms.items():
        hits = list(re.finditer(rf"\b{re.escape(abbr)}\b", prose))
        if not hits:
            continue
        first = hits[0].start()

        # Two satisfaction styles, because the terms are not all the same shape.
        # Letter abbreviations take a parenthetical: "optical character recognition (OCR)".
        # X12 transaction numbers are digits, so a parenthetical reads badly and the book
        # glosses them in prose instead: "an X12 837 claim submission". Checking every term
        # for a parenthetical made the numeric ones unsatisfiable, so a claims recipe would
        # have looped until it exhausted its retries.
        if abbr.isdigit():
            expanded_at = [m.start() for m in re.finditer(rf"X12\s+{re.escape(abbr)}\b", prose)]
        else:
            expanded_at = [
                m.start()
                for m in re.finditer(rf"[A-Za-z][\w,\- ]{{6,80}}\({re.escape(abbr)}\)", prose)
            ]

        if not expanded_at:
            line = prose[:first].count("\n") + 1
            problems.append(f"{path.name}:{line}: {abbr} never expanded (expected: {form})")
            continue

        # The expansion must be at the first use, not buried later in the page. For the
        # numeric terms the gloss contains the number itself, so the first qualifying
        # occurrence IS the first use and comparing positions directly would misfire.
        if abbr.isdigit():
            if min(expanded_at) > first:
                line = prose[:first].count("\n") + 1
                problems.append(
                    f"{path.name}:{line}: {abbr} used bare before its first X12 gloss"
                )
                continue
        elif min(expanded_at) > first:
            line = prose[:first].count("\n") + 1
            exp_line = prose[: min(expanded_at)].count("\n") + 1
            problems.append(
                f"{path.name}:{line}: {abbr} used bare before its expansion on line {exp_line}"
            )
            continue

        # Guard against expanding every occurrence, which would bloat the prose.
        if len(expanded_at) > 1 and not abbr.isdigit():
            problems.append(
                f"{path.name}: {abbr} expanded {len(expanded_at)} times; only the first use should be"
            )
    return problems


def recipes() -> list[str]:
    seen = []
    for f in sorted(glob.glob("chapter*.md")):
        m = re.match(r"(chapter\d+\.\d+)-", f)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", nargs="?", help="e.g. chapter07.03")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--report", action="store_true", help="rank pages worst-first, always exit 0")
    args = ap.parse_args()

    terms = load_terms()
    targets = recipes() if (args.all or args.report) else ([args.recipe] if args.recipe else [])
    if not targets:
        ap.error("give a recipe id, or --all / --report")

    all_problems: dict[str, list[str]] = {}
    for r in targets:
        for page in pages_for(r):
            probs = check_page(page, terms)
            if probs:
                all_problems[page.name] = probs

    if args.report:
        print(f"  in-scope abbreviations: {len(terms)}")
        print(f"  pages checked: {sum(len(pages_for(r)) for r in targets)}")
        print(f"  pages with at least one violation: {len(all_problems)}\n")
        for name, probs in sorted(all_problems.items(), key=lambda kv: -len(kv[1]))[:15]:
            print(f"    {name[:58]:60} {len(probs):3d}")
        total = sum(len(v) for v in all_problems.values())
        print(f"\n  total violations: {total}")
        return 0

    for probs in all_problems.values():
        for p in probs:
            print(f"  {p}")
    if all_problems:
        print(f"\n  FAIL: {sum(len(v) for v in all_problems.values())} violation(s)")
        return 1
    print("  OK: abbreviations expanded on first use")
    return 0


if __name__ == "__main__":
    sys.exit(main())
