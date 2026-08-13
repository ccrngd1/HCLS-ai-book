#!/usr/bin/env python3
"""Add a one-line pointer to the shared PHI-governance page on recipes that need it.

Rather than write 57 variations of the same governance paragraph, every recipe that
sends protected health information to a third-party model, or trains on historical
patient data, gets one standard callout pointing at the single authoritative page,
"Before You Send Protected Health Information Anywhere". That page is front matter in
print and a top-level page on the site, so one line serves both editions.

Reversible by design, like the safety-banner and honest-take passes:

    python3 add_phi_callout.py            # dry run
    python3 add_phi_callout.py --apply
    python3 add_phi_callout.py --remove

Two deliberate choices:
  * The callout names the page rather than linking to it. A markdown link resolves on
    the site but makes the print build warn about an unresolved target, since the page
    is front matter with no slug. Naming it reads correctly in both editions.
  * "protected health information (PHI)" is written pre-expanded, so the R-1 abbreviation
    pass treats it as already done and does not try to expand it again.

Skips any recipe whose R-1 task is in_progress, so it never edits a file ralph has open
in a worktree.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

MARK = "<!-- phi-callout -->"
CALLOUT = (
    f"{MARK}\n"
    "> **Before you build this, settle the data-governance questions.** This recipe moves "
    "protected health information (PHI) through a hosted model or trains on historical "
    "patient data, or both. See \"Before You Send Protected Health Information Anywhere\" at "
    "the front of this book for the vendor and secondary-use questions to put to your own "
    "privacy, security, and legal or compliance teams before any of this reaches a patient."
)

SEND = r"\b(Bedrock|hosted (model|LLM)|Transcribe|Comprehend Medical|Textract|foundation model|Claude|GPT|third-party (model|API))\b"
TRAIN = r"(train(ing|ed)? (a |the )?(model|classifier|policy)|historical (claims|data|encounters|patient)|training (data|set)|retrospective (data|cohort))"
GOV_VENDOR = r"(no-train|not train|training on your|data residency|retention)"
GOV_TRAIN = r"(institutional review board|\bIRB\b|data use agreement|\bDUA\b|de-identif|minimum necessary|secondary use|re-identif)"


def in_flight() -> set[str]:
    """Recipe ids whose R-1 task is currently in_progress, as chapterNN.RR."""
    try:
        tasks = json.loads(Path("tasks.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    out = set()
    for t in tasks:
        if t.get("status") == "in_progress":
            m = re.match(r"ch(\d+)-r(\d+)-abbr", t.get("id", ""))
            if m:
                out.add(f"chapter{int(m.group(1)):02d}.{int(m.group(2)):02d}")
    return out


def main_recipes() -> list[Path]:
    return [
        Path(f)
        for f in sorted(glob.glob("chapter*.md"))
        if re.match(r"chapter\d+\.\d+-", f)
        and not re.search(r"-(todo|architecture|python-example)\.md$", f)
    ]


def needs_callout(recipe: Path) -> bool:
    arch = re.sub(r"chapter(\d+\.\d+)-.*", r"chapter\1-architecture.md", recipe.name)
    both = recipe.read_text(encoding="utf-8")
    if Path(arch).is_file():
        both += Path(arch).read_text(encoding="utf-8")
    vendor = re.search(SEND, both, re.I) and not re.search(GOV_VENDOR, both, re.I)
    train = re.search(TRAIN, both, re.I) and not re.search(GOV_TRAIN, both, re.I)
    return bool(vendor or train)


def recipe_id(name: str) -> str:
    m = re.match(r"(chapter\d+\.\d+)-", name)
    return m.group(1) if m else name


def insert(text: str) -> str:
    """Place the callout after the H1 and any existing banner, before the first section."""
    # after the metadata rule that follows the H1
    m = re.search(r"\n---\n", text)
    i = m.end() if m else text.index("\n") + 1
    # if a safety banner is already there, put this after it
    b = re.search(r"(?m)^> \*\*This recipe is illustrative.*?(?=\n\n)", text[i:], re.S)
    if b:
        i = i + b.end()
    return text[:i] + "\n\n" + CALLOUT + text[i:]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    flight = in_flight()
    added = removed = skipped_flight = present = 0

    for recipe in main_recipes():
        text = recipe.read_text(encoding="utf-8")
        has = MARK in text

        if args.remove:
            if has:
                text = re.sub(r"\n*" + re.escape(MARK) + r".*?(?=\n## |\n#|\Z)", "\n", text, flags=re.S)
                if args.remove:
                    recipe.write_text(text, encoding="utf-8")
                    removed += 1
            continue

        if not needs_callout(recipe):
            continue
        if recipe_id(recipe.name) in flight:
            skipped_flight += 1
            continue
        if has:
            present += 1
            continue
        added += 1
        if args.apply:
            recipe.write_text(insert(text), encoding="utf-8")
        else:
            print(f"  would add: {recipe.name}")

    if args.remove:
        print(f"  removed: {removed}")
    else:
        verb = "added" if args.apply else "would add"
        print(f"\n  {verb}: {added}   already present: {present}   skipped (ralph in flight): {skipped_flight}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
