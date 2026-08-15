#!/usr/bin/env python3
"""Generate the digital copies of shared front-matter pages from the print sources.

Some front-matter pages belong in both editions, but print/ is excluded from the site
build, so the digital edition needs copies at the repo root. Copying by hand creates two
files that drift, which is the failure mode that has already bitten this project: a
generated digest that disagreed with its own tracker row, a stale page count, and a build
cache that hid warnings. So print/frontmatter/*.md are the single sources of truth, the
ones the author edits, and this writes the root copies from them.

    python3 sync_phi_page.py           # regenerate all shared pages
    python3 sync_phi_page.py --check   # exit 1 if any copy is stale

HTML editing notes in the sources are stripped (invisible in a browser but still present in
page source where a reader can find them). Manifest placeholders such as {digital_url} are
substituted so the digital copy matches what the print build renders.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# (print source, digital destination). Add a pair here to share another front page.
PAGES = [
    (Path("print/frontmatter/before-you-send-phi.md"), Path("before-you-send-phi.md")),
    (Path("print/frontmatter/governance-and-responsible-ai.md"),
     Path("governance-and-responsible-ai.md")),
]
MANIFEST = Path("print/manifest.json")


def _subs() -> dict:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n = m["total_recipes_in_digital"]
    return dict(
        title=m["title"], subtitle=m["subtitle"], author=m["author"],
        year=m["copyright_year"], digital_url=m["digital_edition_url"],
        recipe_count=n, extra_recipes=n - 15,
    )


def _header(src: Path) -> str:
    return (
        "<!-- GENERATED FILE. Do not edit.\n"
        f"     Source: {src.as_posix()}\n"
        "     Regenerate: python3 sync_phi_page.py\n"
        "     This page is in both editions; the print source is authoritative. -->\n\n"
    )


def render(src: Path, subs: dict) -> str:
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    for key, value in subs.items():
        text = text.replace("{" + key + "}", str(value))
    return _header(src) + text + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    subs = _subs()
    stale = False
    for src, dst in PAGES:
        if not src.is_file():
            print(f"  source missing: {src}")
            return 1
        want = render(src, subs)
        have = dst.read_text(encoding="utf-8") if dst.is_file() else None
        if args.check:
            if have != want:
                print(f"  STALE: {dst} (run python3 sync_phi_page.py)")
                stale = True
            else:
                print(f"  {dst} is current ({len(want.split())} words)")
        else:
            dst.write_text(want, encoding="utf-8")
            print(f"  wrote {dst} ({len(want.split())} words) from {src}")

    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
