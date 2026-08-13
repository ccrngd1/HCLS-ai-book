#!/usr/bin/env python3
"""Generate the digital copy of the PHI governance page from the print source.

The page belongs in both editions, but print/ is excluded from the site build, so the
digital edition needs a copy at the repo root. Copying it by hand would create two files
that drift, which is the failure mode that has already bitten this project three times
today: a generated digest that disagreed with its own tracker row, a stale page count in
kdp-metadata.md, and a build cache that hid two warnings.

So print/frontmatter/before-you-send-phi.md is the single source of truth, the one the
author edits, and this writes the root copy from it.

    python3 sync_phi_page.py           # regenerate
    python3 sync_phi_page.py --check   # exit 1 if the copy is stale

The editing notes in the print source are HTML comments. The print loader strips them; so
does this, because an HTML comment is invisible in a browser but still sits in the page
source where a reader can find it.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SRC = Path("print/frontmatter/before-you-send-phi.md")
DST = Path("before-you-send-phi.md")

HEADER = (
    "<!-- GENERATED FILE. Do not edit.\n"
    "     Source: print/frontmatter/before-you-send-phi.md\n"
    "     Regenerate: python3 sync_phi_page.py\n"
    "     This page is in both editions; the print source is authoritative. -->\n\n"
)


def render() -> str:
    text = SRC.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    return HEADER + text + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not SRC.is_file():
        print(f"  source missing: {SRC}")
        return 1

    want = render()
    have = DST.read_text(encoding="utf-8") if DST.is_file() else None

    if args.check:
        if have != want:
            print("  STALE: run python3 sync_phi_page.py")
            return 1
        print(f"  {DST} is current ({len(want.split())} words)")
        return 0

    DST.write_text(want, encoding="utf-8")
    print(f"  wrote {DST} ({len(want.split())} words) from {SRC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
