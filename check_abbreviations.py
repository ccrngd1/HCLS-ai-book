#!/usr/bin/env python3
"""Check that abbreviations are spelled out on first use (R-1).

Deterministic gate for the R-1 ralph pass. Exits non-zero on any violation.

    python3 check_abbreviations.py chapter07.03           # first-use check
    python3 check_abbreviations.py chapter07.03 --diff     # plus: nothing else changed
    python3 check_abbreviations.py --report               # ranked, always exit 0

The --diff mode exists because the first trial run showed the prose check alone is not
enough of a guardrail. In four sample recipes the agent also rewrote AWS networking
architecture on a line containing no in-scope term at all, and deleted a "(PHI)"
reference rather than expanding it. Both passed the prose check, because both left the
page's first-use state valid. So --diff compares the working tree against HEAD and fails
any edit that is not an abbreviation expansion.

Rules enforced:
  * First PROSE use of an in-scope abbreviation must carry its expansion, verbatim from
    abbreviations.json, in the canonical casing.
  * Later uses stay bare, so the pass cannot bloat the text.
  * Not prose, and never touched: code fences, inline code, link targets, HTML comments,
    and TABLE ROWS. Tables are compact reference material, and in a 6x9 trim, expanding a
    bold row label like **BAA** into **business associate agreement (BAA)** triples the
    column width. A term appearing only in tables therefore needs no expansion.
  * Python companions are out of scope: illustrative sketches, kept out of the site
    navigation, mostly code, where an abbreviation is an identifier.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

DATA = Path("abbreviations.json")


def load_terms() -> dict[str, str]:
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
    """Blank non-prose while preserving offsets, so reported line numbers stay right."""
    def blank(m: re.Match) -> str:
        return re.sub(r"\S", " ", m.group(0))

    text = re.sub(r"```.*?```", blank, text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", blank, text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", blank, text)
    text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
    # Blank the whole markdown link (label AND target) in one pass. Doing the target
    # first, as an earlier version did, consumed the closing bracket and left the label
    # visible, so abbreviations inside link text were miscounted as prose first-uses.
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", blank, text)        # inline links [label](target)
    text = re.sub(r"\[[^\]]*\]\[[^\]]*\]", blank, text)      # reference links [text][ref]
    text = re.sub(r"\[[^\]]*\]", blank, text)                  # remaining bare [labels] / citations
    text = re.sub(r"^\s{4,}\S.*$", blank, text, flags=re.M)
    text = re.sub(r"^\s*\|.*$", blank, text, flags=re.M)      # table rows
    text = re.sub(r"^#{1,6} .*$", blank, text, flags=re.M)     # headings
    return text


def pages_for(recipe: str) -> list[Path]:
    return [
        Path(p)
        for p in sorted(glob.glob(f"{recipe}-*.md"))
        if not p.endswith(("-todo.md", "-python-example.md"))
    ]


def _expansion_positions(prose: str, abbr: str, form: str) -> list[int]:
    """Where the canonical expansion appears. Case-exact, bar a sentence-initial capital."""
    if abbr.isdigit():
        return [m.start() for m in re.finditer(rf"X12\s+{re.escape(abbr)}\b", prose)]
    variants = {form, form[0].upper() + form[1:]}
    out: list[int] = []
    for v in variants:
        out += [m.start() for m in re.finditer(re.escape(v), prose)]
    return sorted(out)


def check_page(path: Path, terms: dict[str, str]) -> list[str]:
    prose = prose_of(path.read_text(encoding="utf-8"))
    problems: list[str] = []

    for abbr, form in terms.items():
        # A hyphenated continuation makes it a different term: ICD-10, FHIR-based,
        # PHI-bearing. Expanding the bare letters inside one breaks it, which is exactly
        # what the first pass did 81 times.
        hits = [m for m in re.finditer(rf"\b{re.escape(abbr)}\b(?!-\w)", prose)]
        if not hits:
            continue
        first = hits[0].start()
        expanded_at = _expansion_positions(prose, abbr, form)
        line = prose[:first].count("\n") + 1

        if not expanded_at:
            # Distinguish "absent" from "present but miscased or reworded", because the
            # fix is different and a vague message sends the agent hunting.
            loose = re.search(rf"[A-Za-z][\w,\- ]{{6,80}}\({re.escape(abbr)}\)", prose)
            if loose and not abbr.isdigit():
                problems.append(
                    f"{path.name}:{line}: {abbr} expanded as {loose.group(0)!r}; "
                    f"use the canonical form verbatim: {form!r}"
                )
            else:
                problems.append(f"{path.name}:{line}: {abbr} never expanded (expected: {form})")
            continue

        if min(expanded_at) > first:
            problems.append(f"{path.name}:{line}: {abbr} used bare before its expansion")
            continue

        # An expansion dropped in front of an existing parenthetical produces
        # "retrieval-augmented generation (RAG) (Recipe 2.7)", which is poor typography
        # the first-use check cannot see, since the required form is technically present.
        # The sentence needs recasting instead.
        for m in re.finditer(rf"\({re.escape(abbr)}\)\s*\(", prose):
            ln = prose[: m.start()].count("\n") + 1
            problems.append(
                f"{path.name}:{ln}: {abbr} expansion sits next to another parenthetical; "
                "recast the sentence rather than stacking brackets"
            )

        if len(expanded_at) > 1 and not abbr.isdigit():
            problems.append(
                f"{path.name}: {abbr} expanded {len(expanded_at)} times; only the first use should be"
            )
    return problems


def check_diff(recipe: str, terms: dict[str, str]) -> list[str]:
    """Fail any change that is not an abbreviation expansion."""
    names = [p.name for p in pages_for(recipe)]
    if not names:
        return []
    try:
        raw = subprocess.run(
            ["git", "diff", "-U0", "HEAD", "--"] + names,
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout
    except Exception as exc:                                  # pragma: no cover
        return [f"could not read git diff: {exc}"]

    problems: list[str] = []
    current = ""
    for line in raw.split("\n"):
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line or line[0] not in "+-" or line.startswith(("+++", "---")):
            continue
        body = line[1:]
        if not body.strip():
            continue

        # Excluding headings and link labels from prose stopped the checker DEMANDING an
        # expansion there, but never stopped the agent adding one, and 5 leaked through on
        # the next run. These three reject the act, not just the requirement.
        if line[0] == "+":
            if re.search(r"\([A-Z][A-Z0-9]{1,6}\)-\w", body):
                problems.append(
                    f"{current}: expansion inserted inside a compound token, which breaks it "
                    f"(ICD-10, FHIR-based): {body.strip()[:80]}"
                )
                continue
            if re.search(r"\[[^\]]*\([A-Z][A-Z0-9]{1,6}\)[^\]]*\]", body):
                problems.append(
                    f"{current}: expansion inserted inside a link or citation label, which "
                    f"misquotes the source: {body.strip()[:80]}"
                )
                continue
            if re.match(r"\s*#{1,6} ", body) and re.search(r"\([A-Z][A-Z0-9]{1,6}\)", body):
                problems.append(
                    f"{current}: expansion inserted into a heading: {body.strip()[:80]}"
                )
                continue

        # A table row must not be edited at all: tables are out of scope by policy.
        if body.lstrip().startswith("|"):
            problems.append(f"{current}: table row edited, which is out of scope: {body.strip()[:80]}")
            continue

        # Every edited line must involve an in-scope term. This is what catches a
        # technical rewrite dressed up as an abbreviation pass.
        touched = [
            a for a, f in terms.items()
            if re.search(rf"\b{re.escape(a)}\b", body) or f.lower() in body.lower()
        ]
        if not touched:
            problems.append(
                f"{current}: edited a line with no in-scope abbreviation, so it is not part "
                f"of this task: {body.strip()[:80]}"
            )

    # No in-scope term may lose occurrences: expanding must not delete a reference.
    for page in pages_for(recipe):
        old = subprocess.run(
            ["git", "show", f"HEAD:{page.name}"], capture_output=True, text=True, check=False
        ).stdout
        if not old:
            continue
        new = page.read_text(encoding="utf-8")
        for abbr in terms:
            pat = rf"\b{re.escape(abbr)}\b"
            before, after = len(re.findall(pat, old)), len(re.findall(pat, new))
            if after < before:
                problems.append(
                    f"{page.name}: {abbr} occurrences dropped {before} -> {after}; "
                    "expanding must not remove a reference"
                )
    return problems


def recipes() -> list[str]:
    seen: list[str] = []
    for f in sorted(glob.glob("chapter*.md")):
        m = re.match(r"(chapter\d+\.\d+)-", f)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--diff", action="store_true", help="also verify nothing else changed")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    terms = load_terms()
    targets = recipes() if (args.all or args.report) else ([args.recipe] if args.recipe else [])
    if not targets:
        ap.error("give a recipe id, or --all / --report")

    problems: dict[str, list[str]] = {}
    for r in targets:
        for page in pages_for(r):
            probs = check_page(page, terms)
            if probs:
                problems[page.name] = probs
        if args.diff:
            d = check_diff(r, terms)
            if d:
                problems[f"{r} (diff)"] = d

    if args.report:
        print(f"  in-scope abbreviations: {len(terms)}")
        print(f"  pages checked: {sum(len(pages_for(r)) for r in targets)}")
        print(f"  pages with violations: {len(problems)}")
        for name, probs in sorted(problems.items(), key=lambda kv: -len(kv[1]))[:12]:
            print(f"    {name[:58]:60} {len(probs):3d}")
        print(f"\n  total violations: {sum(len(v) for v in problems.values())}")
        return 0

    for probs in problems.values():
        for p in probs:
            print(f"  {p}")
    if problems:
        print(f"\n  FAIL: {sum(len(v) for v in problems.values())} violation(s)")
        return 1
    print("  OK: abbreviations expanded on first use, and nothing else changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
