#!/usr/bin/env python3
"""Finish the last R-1 abbreviation expansions the ralph loop kept no-op-passing.

Ten recipes were left marked passing with a handful of residual violations each: the
worker reported success without editing. The remaining work is mechanical and the
deterministic checker knows exactly where it is, so this finishes it directly.

Driven entirely by check_abbreviations.py's own logic, so it enforces the same rules
(prose only, first use per page, canonical form, no compound/heading/link/table edits):

  - "never expanded": insert the canonical form at the first prose occurrence.
  - "expanded N times": keep the first expansion, revert the rest to the bare abbreviation.

Idempotent and validated: it re-runs the checker per recipe and stops when clean, and
refuses to touch a recipe whose R-1 task is in flight.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ca_spec = importlib.util.spec_from_file_location("ca", "check_abbreviations.py")
ca = importlib.util.module_from_spec(ca_spec)
ca_spec.loader.exec_module(ca)
TERMS = ca.load_terms()


def in_flight() -> set[str]:
    try:
        tasks = json.loads(Path("tasks.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    out = set()
    for t in tasks:
        if t.get("status") == "in_progress":
            m = re.match(r"ch(\d+)-r(\d+)-abbr", t.get("id", ""))
            if m:
                out.add(f"chapter{int(m.group(1))}.{int(m.group(2))}")
    return out


def first_prose_index(raw: str, abbr: str) -> int | None:
    prose = ca.prose_of(raw)
    m = re.search(rf"\b{re.escape(abbr)}\b(?!-\w)", prose)
    return m.start() if m else None


def expansion_indices(raw: str, abbr: str, form: str) -> list[int]:
    prose = ca.prose_of(raw)
    return ca._expansion_positions(prose, abbr, form)


def fix_page(path: Path) -> int:
    """Apply one pass of fixes to a page. Returns number of edits made."""
    raw = path.read_text(encoding="utf-8")
    edits = 0
    for abbr, form in TERMS.items():
        probs = [p for p in ca.check_page(path, TERMS) if re.search(rf"\b{re.escape(abbr)}\b", p)]
        # recompute against current raw each abbr to keep offsets valid
        page_probs = ca.check_page(path, TERMS)
        mine = [p for p in page_probs if f": {abbr} " in p or f":{abbr} " in p or f" {abbr} " in p]
        if not mine:
            continue

        if any("never expanded" in p for p in mine):
            i = first_prose_index(raw, abbr)
            if i is not None:
                raw = raw[:i] + form + raw[i + len(abbr):]
                edits += 1
        elif any("expanded" in p and "times" in p for p in mine):
            # keep the first expansion, revert the rest to bare abbr
            idxs = expansion_indices(raw, abbr, form)
            for start in sorted(idxs, reverse=True)[:-1]:  # all but the earliest
                # only revert the canonical form, exact-length
                variants = {form, form[0].upper() + form[1:]}
                for v in variants:
                    if raw[start:start + len(v)] == v:
                        raw = raw[:start] + abbr + raw[start + len(v):]
                        edits += 1
                        break
        if edits:
            path.write_text(raw, encoding="utf-8")
            return edits  # one edit at a time; caller re-runs
    if edits:
        path.write_text(raw, encoding="utf-8")
    return edits


def recipe_pages(recipe: str) -> list[Path]:
    return ca.pages_for(recipe)


def main(recipes: list[str]) -> int:
    flight = in_flight()
    total = 0
    for recipe in recipes:
        if recipe in flight:
            print(f"  SKIP {recipe}: in flight")
            continue
        for _ in range(20):  # safety cap
            pages = recipe_pages(recipe)
            made = 0
            for p in pages:
                made += fix_page(p)
            if made == 0:
                break
            total += made
        # validate
        remaining = sum(len(ca.check_page(p, TERMS)) for p in recipe_pages(recipe))
        status = "clean" if remaining == 0 else f"STILL {remaining} — inspect"
        print(f"  {recipe}: {status}")
    print(f"\n  total edits: {total}")
    return 0


if __name__ == "__main__":
    default = ["chapter04.09","chapter12.03","chapter01.10","chapter10.02","chapter08.10",
               "chapter13.04","chapter03.09","chapter07.07","chapter10.01","chapter11.02"]
    sys.exit(main(sys.argv[1:] or default))
