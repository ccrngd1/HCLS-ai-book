#!/usr/bin/env python3
"""Split a main recipe MD into a story/concepts file + an architecture companion.

Part 1 (stays in the main recipe, "the book"):
  preamble, The Problem, The Technology, General Architecture Pattern,
  The Honest Take, Related Recipes, Tags (+ trailing nav footer)

Part 2 (moves to chapterNN.RR-architecture.md):
  The AWS Implementation, Why This Isn't Production-Ready,
  Variations and Extensions, Additional Resources, Estimated Implementation Time

Usage:  python3 split_recipe.py <main-recipe.md> [--apply]
Without --apply it only reports what it would do.

The original is git-tracked; recover with `git restore <file>` if needed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Section titles (exact H2 text, no leading "## ") that move to the companion.
ARCH_TITLES = [
    "The AWS Implementation",
    "Why This Isn't Production-Ready",
    "Variations and Extensions",
    "Additional Resources",
    "Estimated Implementation Time",
]

# Files that are not recipes and must never be split.
EXCLUDE = {
    "chapter01-executive-summary.md",
    "chapter01-index.md",
}


def split_sections(text: str):
    """Return (preamble, [(title, body), ...]) splitting on fence-aware H2s."""
    lines = text.split("\n")
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    cur_title = None
    cur_body: list[str] = []

    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        is_h2 = (not in_fence) and re.match(r"^## (?!#)", line)
        if is_h2:
            if cur_title is None:
                preamble = cur_body
            else:
                sections.append((cur_title, cur_body))
            cur_title = line[3:].strip()
            cur_body = [line]
        else:
            cur_body.append(line)
    if cur_title is None:
        preamble = cur_body
    else:
        sections.append((cur_title, cur_body))
    return preamble, sections


def derive_names(main_path: Path):
    """Return dict of link targets derived from the main filename."""
    stem = main_path.stem  # e.g. chapter03.01-duplicate-claim-detection
    m = re.match(r"(chapter(\d+)\.(\d+))-(.+)", stem)
    if not m:
        raise ValueError(f"Unexpected recipe filename: {stem}")
    prefix = m.group(1)              # chapter03.01
    chap = m.group(2)                # 03
    return {
        "main": stem,
        "arch": f"{prefix}-architecture",
        "python": f"{prefix}-python-example",
        "preface": f"chapter{chap}-preface",
        "recipe_num": f"{int(m.group(2))}.{int(m.group(3))}",
        "arch_filename": f"{prefix}-architecture.md",
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 split_recipe.py <main-recipe.md> [--apply]")
        return 1
    main_path = Path(sys.argv[1])
    apply = "--apply" in sys.argv
    if main_path.name in EXCLUDE:
        print(f"  SKIP (excluded, not a recipe): {main_path.name}")
        return 0
    names = derive_names(main_path)

    text = main_path.read_text(encoding="utf-8")
    preamble, sections = split_sections(text)
    titles = [t for t, _ in sections]

    arch_set = set(ARCH_TITLES)
    main_secs = [(t, b) for t, b in sections if t not in arch_set]
    arch_secs = [(t, b) for t, b in sections if t in arch_set]

    missing = arch_set - set(titles)
    if missing:
        print(f"  WARNING: expected sections not found: {sorted(missing)}")

    # Derive a clean recipe display name from the H1.
    h1 = next((l for l in preamble if l.startswith("# ")), "# Recipe")
    display = h1.lstrip("# ").replace("\u2b50", "").strip()  # drop star

    # --- Build MAIN: preamble + part1 sections, with a companion callout
    #     appended to the end of the General Architecture Pattern section. ---
    callout = (
        "\n> **The AWS build lives in a companion page.** This recipe covers the "
        "problem, the underlying technology, and the vendor-agnostic architecture. "
        "For the AWS services, architecture diagram, prerequisites, and the "
        f"step-by-step pseudocode walkthrough, see the "
        f"[Architecture and Implementation companion]({names['arch']}). The Python "
        "example is linked from there.\n"
    )
    main_out = list(preamble)
    for t, body in main_secs:
        chunk = list(body)
        if t == "General Architecture Pattern":
            chunk.append(callout)
        main_out.extend(chunk)

    # --- Build ARCH: title + backlink + part2 sections + footer ---
    arch_header = [
        f"# Recipe {names['recipe_num']} Architecture and Implementation: "
        f"{display.split(':',1)[-1].strip() if ':' in display else display}",
        "",
        f"*Companion to [{display}]({names['main']}). This page covers the AWS "
        "architecture, services, prerequisites, and pseudocode. For the problem "
        "framing and the conceptual approach, start with the main recipe.*",
        "",
        "---",
        "",
    ]
    arch_footer = [
        "",
        "---",
        "",
        f"*\u2190 [Main Recipe {names['recipe_num']}]({names['main']}) \u00b7 "
        f"[Python Example]({names['python']}) \u00b7 "
        f"[Chapter Preface]({names['preface']})*",
        "",
    ]
    arch_out = list(arch_header)
    for t, body in arch_secs:
        arch_out.extend(body)
    arch_out.extend(arch_footer)

    main_text = "\n".join(main_out).rstrip() + "\n"
    arch_text = "\n".join(arch_out).rstrip() + "\n"

    # Report
    print(f"  recipe: {names['recipe_num']}  ({display})")
    print(f"  main sections kept: {[t for t,_ in main_secs]}")
    print(f"  arch sections moved: {[t for t,_ in arch_secs]}")
    print(f"  main words: {len(text.split())} -> {len(main_text.split())}")
    print(f"  arch words: {len(arch_text.split())}")
    print(f"  word reconciliation: orig={len(text.split())} "
          f"split-sum={len(main_text.split())+len(arch_text.split())} "
          f"(split adds callout+headers)")

    if apply:
        Path(names["arch_filename"]).write_text(arch_text, encoding="utf-8")
        main_path.write_text(main_text, encoding="utf-8")
        print(f"  WROTE {names['arch_filename']} and rewrote {main_path.name}")
    else:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
