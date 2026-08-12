#!/usr/bin/env python3
"""Move embedded review-artifact TODOs out of published pages into -todo.md files.

The findings-resolution runs left comments like
``// TODO (TechWriter): Expert review S1 (HIGH). Specify the ...`` inside
architecture and Python companion pages. Those pages are published, so a reader
sees the authoring process, including the persona name and a review severity.

The content is genuine, actionable engineering work, so it is relocated rather
than deleted: each block is appended to the recipe's ``chapterNN.RR-todo.md``
under a ``## relocated from published pages`` heading, tagged ``[NEEDS HUMAN]``
so it sorts with the other deferrals, and carries the source file and line.

Idempotent: blocks already present in a todo file are not appended twice.
Dry run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

# "// TODO (Persona): rest" or "# TODO (Persona): rest"
START = re.compile(r"^(?P<indent>[ \t]*)(?P<c>//|#)\s*TODO\s*\((?P<who>[^)]+)\)\s*:?\s*(?P<rest>.*)$")
HEADING = "## relocated from published pages"


def _todo_path(src: Path) -> Path | None:
    """chapter04.10-architecture.md -> chapter04.10-todo.md"""
    m = re.match(r"(chapter\d+\.\d+)-", src.name)
    if not m:
        return None
    return src.with_name(f"{m.group(1)}-todo.md")


def _collect(lines: list[str], i: int) -> tuple[int, list[str]]:
    """Return (index after block, comment text lines) for the block starting at i."""
    m = START.match(lines[i])
    assert m
    comment = m.group("c")
    body = [m.group("rest").strip()]
    j = i + 1
    cont = re.compile(rf"^[ \t]*{re.escape(comment)}\s?(.*)$")
    while j < len(lines):
        cm = cont.match(lines[j])
        if not cm or not lines[j].strip():
            break
        # a new TODO starts a new block
        if START.match(lines[j]):
            break
        body.append(cm.group(1).strip())
        j += 1
    return j, [b for b in body if b]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--glob", default="chapter*.md")
    args = ap.parse_args()

    files = [
        Path(f)
        for f in sorted(glob.glob(args.glob))
        if not f.endswith("-todo.md")
    ]
    pending: dict[Path, list[str]] = {}
    edits: dict[Path, str] = {}
    moved = skipped = 0

    for src in files:
        text = src.read_text(encoding="utf-8")
        if "TODO" not in text:
            continue
        lines = text.splitlines()
        out: list[str] = []
        i = 0
        found = []
        while i < len(lines):
            m = START.match(lines[i])
            if not m:
                out.append(lines[i])
                i += 1
                continue
            j, body = _collect(lines, i)
            found.append((i + 1, m.group("who").strip(), " ".join(body)))
            i = j  # drop the block
        if not found:
            continue
        dest = _todo_path(src)
        if dest is None or not dest.exists():
            print(f"  SKIP (no todo file): {src.name}")
            skipped += len(found)
            continue
        existing = dest.read_text(encoding="utf-8")
        rows = []
        for lineno, who, body in found:
            row = f"- [NEEDS HUMAN] **L{lineno}** ({src.name}, was an inline `{who}` comment) - {body}"
            if body and body[:60] in existing:
                continue
            rows.append(row)
            moved += 1
        if rows:
            pending.setdefault(dest, []).extend(rows)
        edits[src] = "\n".join(out).rstrip("\n") + "\n"
        print(f"  {src.name}: {len(found)} block(s) -> {dest.name}")

    if args.apply:
        for src, new in edits.items():
            src.write_text(new, encoding="utf-8")
        for dest, rows in pending.items():
            t = dest.read_text(encoding="utf-8").rstrip("\n")
            if HEADING not in t:
                t += f"\n\n{HEADING}\n\n"
            else:
                t += "\n"
            t += "\n".join(rows) + "\n"
            dest.write_text(t, encoding="utf-8")

    verb = "moved" if args.apply else "would move"
    print(f"\n  blocks {verb}: {moved}")
    print(f"  skipped (no todo file): {skipped}")
    if not args.apply:
        print("  (dry run; pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
