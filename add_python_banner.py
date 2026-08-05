#!/usr/bin/env python3
"""Insert a uniform "illustrative only" banner into every Python companion page.

The Python companions are deliberately excluded from site navigation and are not
maintained. Each page already carries a bespoke disclaimer of varying shape and
wording; this adds one short, uniform, dated banner immediately after the H1 so
the status is unmissable and greppable.

Idempotent: keyed on the HTML comment marker, so re-running changes nothing.

Usage:
  python3 add_python_banner.py            # dry run
  python3 add_python_banner.py --apply    # write
  python3 add_python_banner.py --revert   # remove the banner again
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

MARKER = "<!-- illustrative-only-banner -->"

BANNER = f"""{MARKER}
> **Illustrative only, and not maintained.** This page exists to show the *shape* of
> an implementation and nothing more. It is not production code, it is not exercised by
> any test suite, and it pins no dependency versions. Cloud APIs, SDK signatures, IAM
> actions, and model identifiers all change frequently, so assume anything specific
> below is already out of date. Verify every call, permission, and model identifier
> against current vendor documentation before relying on it. Trust this page for
> understanding how the pieces fit together, and for nothing else. It is intentionally
> left out of the site navigation for this reason. Last reviewed 2026-08."""


def main() -> int:
    apply = "--apply" in sys.argv
    revert = "--revert" in sys.argv
    files = sorted(glob.glob("chapter*-python-example.md"))

    changed = skipped = 0
    for name in files:
        p = Path(name)
        text = p.read_text(encoding="utf-8")

        if revert:
            if MARKER not in text:
                skipped += 1
                continue
            lines = text.split("\n")
            start = next(i for i, ln in enumerate(lines) if ln.strip() == MARKER)
            end = start
            while end < len(lines) and (lines[end].startswith(">") or lines[end].strip() == MARKER):
                end += 1
            # also drop the single blank separator we inserted
            if end < len(lines) and lines[end].strip() == "":
                end += 1
            del lines[start:end]
            if apply:
                p.write_text("\n".join(lines), encoding="utf-8")
            changed += 1
            continue

        if MARKER in text:
            skipped += 1
            continue

        lines = text.split("\n")
        if not lines or not lines[0].startswith("# Recipe"):
            print(f"  WARN: unexpected header, skipping {name}")
            skipped += 1
            continue

        # Insert after the H1, followed by a blank line.
        lines[1:1] = ["", *BANNER.split("\n")]
        if apply:
            p.write_text("\n".join(lines), encoding="utf-8")
        changed += 1

    verb = "reverted" if revert else "banner added to"
    action = verb if apply else f"would be {verb.replace('added to', 'added to')}"
    print(f"  python companion pages found: {len(files)}")
    print(f"  {action}: {changed}")
    print(f"  already correct, skipped:     {skipped}")
    if not apply:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
