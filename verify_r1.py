#!/usr/bin/env python3
"""Verify R-1 completion against the checker rather than against task status.

Task status is not trustworthy for this pass. In the first run, 15 tasks logged
"no changes to commit": the worker reported outcome=pass while producing zero edits, and
the orchestrator recorded that self-report as success. Four of those recipes were never
touched by any commit yet counted as done. Separately, repairing the compound-token damage
legitimately reopened violations on recipes that had already passed, because reverting an
expansion out of a heading removed the page's only expansion of that term.

So the source of truth is check_abbreviations.py, not tasks.json. This script reconciles
the two: any task whose recipe still has violations goes back to pending, whatever its
status claims.

    python3 verify_r1.py            # report only
    python3 verify_r1.py --reset    # also reset tasks whose recipes are not clean

Run it after every loop, and treat R-1 as finished only when outstanding reaches zero.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

TASKS = Path("tasks.json")
RUN_ID = "r1-abbreviations"


def load_checker():
    spec = importlib.util.spec_from_file_location("ca", "check_abbreviations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def recipe_of(task_id: str) -> str | None:
    m = re.match(r"ch(\d+)-r(\d+)-abbr$", task_id)
    return f"chapter{m.group(1)}.{m.group(2)}" if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    ca = load_checker()
    terms = ca.load_terms()
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))

    clean: list[str] = []
    dirty: list[tuple[str, str, int]] = []
    for t in tasks:
        if t.get("spilled_run_id") != RUN_ID:
            continue
        recipe = recipe_of(t["id"])
        if not recipe:
            continue
        n = sum(len(ca.check_page(p, terms)) for p in ca.pages_for(recipe))
        (clean if n == 0 else dirty).append(t["id"] if n == 0 else (t["id"], t["status"], n))

    total = len(clean) + len(dirty)
    print(f"  R-1 recipes: {total}")
    print(f"    clean:       {len(clean)}")
    print(f"    outstanding: {len(dirty)}   violations: {sum(n for _, _, n in dirty)}")
    by_status = collections.Counter(s for _, s, _ in dirty)
    print(f"    outstanding by recorded status: {dict(by_status)}")

    mislabelled = [(i, n) for i, s, n in dirty if s == "passing"]
    if mislabelled:
        print(f"\n  {len(mislabelled)} task(s) recorded as passing but not actually clean:")
        for i, n in sorted(mislabelled, key=lambda x: -x[1])[:10]:
            print(f"    {i:16} {n:3d} violation(s)")

    if not args.reset:
        if dirty:
            print("\n  run with --reset to requeue these")
        return 1 if dirty else 0

    ids = {i for i, _, _ in dirty}
    n = 0
    for t in tasks:
        if t["id"] in ids and t["status"] != "pending":
            t["status"] = "pending"
            t["retry_count"] = 0
            n += 1
    TASKS.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    print(f"\n  requeued: {n}")
    print(f"  pending now: {sum(1 for t in tasks if t['status'] == 'pending')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
