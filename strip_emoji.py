#!/usr/bin/env python3
"""Remove decorative emoji from book content, in both editions.

Rationale: the embedded print face (Gelasio) contains no pictographic, star,
circle, or geometric-shape glyphs, so emoji either drop out of the PDF or
silently fall back to a monospace face mid-line. They are also decorative in
every observed case: Mermaid node labels, Python print() strings, and callout
headings all carry the meaning in the adjacent text.

DELIBERATELY PRESERVED (verified present in DejaVu Sans Mono and used only
inside fenced code blocks, where the mono face renders them):
  box drawing U+2500-U+257F, and the diagram glyphs
  BLACK DOWN-POINTING TRIANGLE (580 uses), BLACK RIGHT-POINTING POINTER,
  CHECK MARK, BALLOT X
Also preserved, because they are typography or content rather than emoji:
  arrows (nav footers and prose), middle dot, dashes, math symbols, Greek
  letters, accented Latin, and CJK (the multilingual interpretation recipe).

Idempotent. Usage:
  python3 strip_emoji.py            # dry run
  python3 strip_emoji.py --apply
"""
from __future__ import annotations

import glob
import re
import sys
from collections import Counter
from pathlib import Path

# Pictographic emoji + the specific non-pictographic symbols that are purely
# decorative here. Note U+FE0F (variation selector) must go with them.
EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # symbols & pictographs, emoticons, transport, supplemental
    "\U0001F000-\U0001F2FF"   # mahjong/domino/enclosed alphanumerics
    "\u2B50"                  # white medium star
    "\u274C\u2705"            # cross mark, white heavy check mark
    "\u2764"                  # heavy black heart
    "\u26A0"                  # warning sign
    "\u2695"                  # staff of aesculapius
    "\u200D"                  # zero-width joiner (emoji sequences)
    "\uFE0F"                  # variation selector-16
    "]"
)


def clean(text: str) -> tuple[str, int]:
    n = len(EMOJI.findall(text))
    if not n:
        return text, 0
    out = EMOJI.sub("", text)
    # Tidy artifacts left behind by removal.
    out = re.sub(r"\[ +", "[", out)          # Mermaid: A[ Label] -> A[Label]
    out = re.sub(r"[ \t]{2,}", " ", out)     # collapse runs of spaces
    out = re.sub(r'(["\'])\s+([.,!?])', r"\1\2", out)
    out = re.sub(r"[ \t]+$", "", out, flags=re.M)  # trailing whitespace
    return out, n


def main() -> int:
    apply = "--apply" in sys.argv

    targets = [f for f in sorted(glob.glob("chapter*.md")) if not f.endswith("-todo.md")]
    for extra in ("README.md", "Home.md", "SUMMARY.md", "_Sidebar.md",
                  "RECIPE-GUIDE.md", "STYLE-GUIDE.md"):
        if Path(extra).exists():
            targets.append(extra)

    stats = Counter()
    per_char = Counter()
    for path in targets:
        p = Path(path)
        original = p.read_text(encoding="utf-8")
        per_char.update(EMOJI.findall(original))
        new, n = clean(original)
        if n:
            stats["files"] += 1
            stats["emoji"] += n
            if apply:
                p.write_text(new, encoding="utf-8")

    print("  " + ("APPLIED" if apply else "DRY RUN"))
    print(f"    files scanned:  {len(targets)}")
    print(f"    files changed:  {stats['files']}")
    print(f"    emoji removed:  {stats['emoji']}")
    if per_char:
        print("    by character:")
        for ch, n in per_char.most_common():
            print(f"      {ch!r} U+{ord(ch):04X}  {n}")
    if not apply:
        print("  (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
