#!/usr/bin/env python3
"""Add a per-recipe vendor data-handling note to architecture companions (R-12).

R-12: recipes that send PHI to a hosted model or managed AI service should carry a
concrete, co-located reminder to settle the vendor's train/retention/residency terms,
beyond the general pointer the front-of-book PHI page and the recipe callouts provide.

Deterministic and reversible, like add_phi_callout.py, because the note is a canonical
block, not generated prose. Ralph is unnecessary here and its judgment adds nothing.

    python3 add_vendor_notes.py            # dry run
    python3 add_vendor_notes.py --apply
    python3 add_vendor_notes.py --remove

Placement: a blockquote right after the companion's H1. The note uses BARE "PHI" and
"BAA" because the companions expand them in their own BAA tables, so expanding again
here would create an R-1 double-expansion. Vendor-neutral about WHICH service, since the
surrounding companion already names it and service detection is unreliable.
"""
from __future__ import annotations
import argparse, glob, re, sys
from pathlib import Path

MARK = "<!-- vendor-note -->"
NOTE = (
    f"{MARK}\n"
    "> **Confirm the vendor's data-handling terms before you build.** This recipe sends "
    "protected health information to a hosted model or managed AI service. For the "
    "specific service you choose, confirm whether it is covered by your business associate "
    "agreement, whether it trains on your inputs and how you opt out, and how long inputs "
    "are retained and where. These are contract-and-configuration questions, not model "
    "questions. See \"Before You Send Protected Health Information Anywhere\" for the full "
    "set of questions to take to your privacy, security, and legal or compliance teams."
)

SEND = r"\b(Bedrock|hosted (model|LLM)|Transcribe|Comprehend Medical|Textract|foundation model|Claude|GPT)\b"
GOV = r"(no-train|not train|training on your|does not train|data residency|zero.?day retention|opt out of training|retention (window|period|policy))"


def scope() -> list[Path]:
    out = []
    for f in sorted(glob.glob("chapter*.md")):
        if not re.match(r"chapter\d+\.\d+-", f) or re.search(r"-(todo|python-example)\.md$", f):
            continue
        if f.endswith("-architecture.md"):
            continue
        arch = re.sub(r"chapter(\d+\.\d+)-.*", r"chapter\1-architecture.md", f)
        both = Path(f).read_text(encoding="utf-8")
        if Path(arch).is_file():
            both += Path(arch).read_text(encoding="utf-8")
        if re.search(SEND, both, re.I) and not re.search(GOV, both, re.I):
            if Path(arch).is_file():
                out.append(Path(arch))
    return out


def insert(text: str) -> str:
    m = re.search(r"(?m)^# .*$", text)
    i = text.index("\n", m.end()) + 1 if m else 0
    return text[:i] + "\n" + NOTE + "\n" + text[i:]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--remove", action="store_true")
    ap.add_argument("only", nargs="*")
    args = ap.parse_args()

    targets = scope()
    if args.only:
        targets = [p for p in targets if any(o in p.name for o in args.only)]
    added = removed = present = 0
    for p in targets:
        t = p.read_text(encoding="utf-8")
        if args.remove:
            if MARK in t:
                t = re.sub(r"\n*" + re.escape(MARK) + r".*?(?=\n#|\n##|\Z)", "\n", t, flags=re.S)
                p.write_text(t, encoding="utf-8"); removed += 1
            continue
        if MARK in t:
            present += 1; continue
        added += 1
        if args.apply:
            p.write_text(insert(t), encoding="utf-8")
        else:
            print(f"  would add: {p.name}")
    if args.remove:
        print(f"  removed: {removed}")
    else:
        print(f"  {'added' if args.apply else 'would add'}: {added}   already present: {present}   in scope: {len(targets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
