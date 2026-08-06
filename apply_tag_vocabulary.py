#!/usr/bin/env python3
"""Apply the controlled tag vocabulary in tag-vocabulary.json to every recipe.

For each recipe's Tags section: map each tag to its canonical form (identity or
alias), drop anything outside the vocabulary, de-duplicate, order by facet, and
cap at max_tags_per_recipe. Tags are emitted one line, backtick-quoted, separated
by " · ", matching the existing house format.

Recipes with no Tags section are reported, not invented: assigning tags to those
needs a read of the recipe, so they are listed for a follow-up pass.

Idempotent. Usage:
  python3 apply_tag_vocabulary.py            # dry run with a preview
  python3 apply_tag_vocabulary.py --apply
"""
from __future__ import annotations

import collections
import glob
import json
import re
import sys
from pathlib import Path

VOCAB = "tag-vocabulary.json"
TAGS_BLOCK = re.compile(r"(^## Tags\s*\n)(.+?)(?=\n##|\n---|\Z)", re.S | re.M)


def load():
    v = json.load(open(VOCAB, encoding="utf-8"))
    order, canon, facet_of = [], set(), {}
    for facet, ts in v["facets"].items():
        for t in ts:
            if t not in canon:
                order.append(t)
                canon.add(t)
                facet_of[t] = facet
    alias = {k.strip(): val.strip() for k, val in v["aliases"].items()}
    return canon, order, alias, facet_of, int(v["max_tags_per_recipe"])


def select(tags: list[str], facet_of: dict, facet_order: list[str], cap: int) -> list[str]:
    """Trim to cap by taking round-robin across facets.

    Truncating in facet order would strip the AWS service tags (last facet) from
    exactly the recipes that have the most to say, which is backwards: service
    tags are among the most useful for discovery. Round-robin keeps every facet
    represented.
    """
    if len(tags) <= cap:
        return tags
    buckets = {f: [t for t in tags if facet_of.get(t) == f] for f in facet_order}
    out = []
    while len(out) < cap:
        progressed = False
        for f in facet_order:
            if buckets[f] and len(out) < cap:
                out.append(buckets[f].pop(0))
                progressed = True
        if not progressed:
            break
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    canon, order, alias, facet_of, cap = load()
    rank = {t: i for i, t in enumerate(order)}
    facet_order = list(json.load(open(VOCAB, encoding='utf-8'))['facets'])

    mains = [
        f for f in sorted(glob.glob("chapter*.md"))
        if not re.search(
            r"-(todo|architecture|python-example|preface|index|executive-summary)\.md$", f
        )
    ]

    dropped = collections.Counter()
    changed = notags = 0
    capped = []
    before_total = after_total = 0
    preview = []

    for path in mains:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        m = TAGS_BLOCK.search(text)
        if not m:
            notags += 1
            continue
        head, block = m.group(1), m.group(2)
        raw = [x.lower().strip() for x in re.findall(r"`([^`]+)`", block)]
        before_total += len(raw)

        out = []
        for t in raw:
            c = t if t in canon else alias.get(t)
            if c is None:
                dropped[t] += 1
                continue
            if c not in out:
                out.append(c)
        # Select while still in the author's original order, so that within a
        # facet the tags they listed first (the primary ones) survive the cap.
        if len(out) > cap:
            capped.append((path, len(out)))
            out = select(out, facet_of, facet_order, cap)
        out.sort(key=lambda t: rank.get(t, 10**6))
        after_total += len(out)

        trailing = "\n" if block.endswith("\n") else ""
        new_block = " · ".join(f"`{t}`" for t in out) + trailing
        if new_block != block:
            changed += 1
            if len(preview) < 3:
                preview.append((Path(path).name, raw, out))
            if apply:
                p.write_text(text[: m.start()] + head + new_block + text[m.end():],
                             encoding="utf-8")

    print("  " + ("APPLIED" if apply else "DRY RUN"))
    print(f"    recipes changed          {changed}")
    print(f"    tag occurrences          {before_total} -> {after_total}")
    print(f"    distinct dropped tags    {len(dropped)} ({sum(dropped.values())} occurrences)")
    print(f"    recipes over the cap     {len(capped)}")
    for path, n in sorted(capped, key=lambda kv: -kv[1])[:5]:
        print(f"      {Path(path).name[:52]:54s} had {n}")
    print(f"    recipes with NO Tags     {notags} (left alone; need a content read)")

    for name, raw, out in preview:
        print(f"\n    {name}")
        print(f"      before ({len(raw):3d}): {' · '.join(raw[:12])}{' ...' if len(raw)>12 else ''}")
        print(f"      after  ({len(out):3d}): {' · '.join(out)}")

    if not apply:
        print("\n  (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
