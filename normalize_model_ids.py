#!/usr/bin/env python3
"""Normalize hard-coded Bedrock model IDs across the recipe corpus.

Problem: the corpus mixes 2024-era model IDs with current ones, so the book
contradicts itself about which models exist. Some IDs are also malformed
(e.g. a 4-6 model carrying claude-3-sonnet's 2024-02-29 date stamp).

Approach: collapse each stale ID onto the current ID for the SAME capability
tier, preserving the fast/reasoning distinction that the examples teach. Every
replacement target already appears elsewhere in the book, so this invents no
identifiers. Undated aliases are preferred over date-stamped ones because they
drift less.

NOT done here: verifying these IDs are currently available in Bedrock. That is
deliberately a build-time check, per the banner on every Python page.

Usage:
  python3 normalize_model_ids.py            # dry run
  python3 normalize_model_ids.py --apply    # write
"""
from __future__ import annotations

import glob
import re
import sys
from collections import Counter
from pathlib import Path

FAST = "anthropic.claude-haiku-4-5-v1:0"
REASONING = "anthropic.claude-sonnet-4-6-v1:0"

# Exact-string replacements, applied in order.
REPLACEMENTS: list[tuple[str, str, str]] = [
    # stale fast tier -> current fast tier
    ("anthropic.claude-3-5-haiku-20241022-v1:0", FAST, "stale 2024 fast-tier ID"),
    ("anthropic.claude-3-haiku-20240307-v1:0", FAST, "stale 2024 fast-tier ID"),
    # stale reasoning tier -> current reasoning tier
    ("anthropic.claude-3-5-sonnet-20241022-v2:0", REASONING, "stale 2024 reasoning ID"),
    ("anthropic.claude-3-5-sonnet-20240620-v1:0", REASONING, "stale 2024 reasoning ID"),
    ("anthropic.claude-3-sonnet-20240229-v1:0", REASONING, "stale 2024 reasoning ID"),
    # malformed: 4-6 model stamped with claude-3-sonnet's date
    ("anthropic.claude-sonnet-4-6-20240229-v1:0", REASONING, "malformed date stamp"),
    # prefer the undated alias over a date-stamped one
    ("anthropic.claude-sonnet-4-6-20260217-v1:0", REASONING, "date-stamped -> undated alias"),
]

# Regex fixes applied after the exact replacements.
REGEX_FIXES: list[tuple[str, str, str]] = [
    # bare "-v1" missing the ":0" suffix, without touching correct "-v1:0"
    (r"anthropic\.claude-sonnet-4-6-v1(?!:0)", REASONING, "missing :0 suffix"),
]

# Intentionally left alone:
#   amazon.titan-embed-text-v2:0            (embedding model, plausible and current)
#   anthropic.claude-opus-4-6-20260204-v1:0 (no undated alias appears in the book,
#                                            so collapsing it would invent an ID)
#   anthropic.claude-XX / claude-sonnet-... (already-generic placeholders)


def main() -> int:
    apply = "--apply" in sys.argv
    files = sorted(
        glob.glob("chapter*-python-example.md") + glob.glob("chapter*-architecture.md")
    )

    tally: Counter[str] = Counter()
    touched: set[str] = set()

    for name in files:
        p = Path(name)
        text = original = p.read_text(encoding="utf-8")

        for old, new, reason in REPLACEMENTS:
            if old in text:
                n = text.count(old)
                text = text.replace(old, new)
                tally[f"{old}  ->  {new}  [{reason}]"] += n

        for pattern, new, reason in REGEX_FIXES:
            hits = len(re.findall(pattern, text))
            if hits:
                text = re.sub(pattern, new, text)
                tally[f"/{pattern}/  ->  {new}  [{reason}]"] += hits

        if text != original:
            touched.add(name)
            if apply:
                p.write_text(text, encoding="utf-8")

    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}  {k}")
    print(f"\n  files scanned: {len(files)}")
    print(f"  files {'changed' if apply else 'that would change'}: {len(touched)}")
    print(f"  total replacements: {sum(tally.values())}")
    if not apply:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
