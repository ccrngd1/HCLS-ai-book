#!/usr/bin/env python3
"""Fix broken internal links in the cookbook (dry-run unless --apply).

Categories handled (link rewrites only; no content fabrication):
  1. chapterNN-index  -> chapterNN-preface   (overview pages never existed
     except ch01; the preface is the chapter landing page). ch12 excluded
     because it has no preface yet (content gap, handled separately).
  2. deleted duplicate names -> canonical names.
  3. legacy ch01 -v2/-v3/-python names -> real filenames.
  4. slightly-wrong recipe names -> real filenames.

Every replacement is an exact string swap of the link target inside
markdown link parens, so labels and surrounding prose are untouched.
"""
import glob
import re
import sys
from pathlib import Path

# --- explicit target rewrites: old_target -> new_target -------------------
EXACT = {
    # deleted duplicates -> canonical
    "chapter08.03-icd10-code-suggestion": "chapter08.03-icd-10-code-suggestion",
    "chapter09.10-multi-modal-imaging-fusion": "chapter09.10-multi-modal-imaging-fusion-analysis",
    "chapter14.05-or-block-scheduling": "chapter14.05-operating-room-block-scheduling",
    # legacy ch01 v2/v3/python names -> real files
    "chapter01.04-prior-auth-python-v2": "chapter01.04-python-example",
    "chapter01.04-prior-auth-v2": "chapter01.04-prior-auth-document-processing",
    "chapter01.05-claims-attachment-python-v2": "chapter01.05-python-example",
    "chapter01.05-claims-attachment-v3": "chapter01.05-claims-attachment-processing",
    "chapter01.06-handwritten-notes-python": "chapter01.06-python-example",
    "chapter01.06-handwritten-notes-v3": "chapter01.06-handwritten-clinical-note-digitization",
    "chapter01.09-medical-records-python-v3": "chapter01.09-python-example",
    "chapter01.09-medical-records-python-v1": "chapter01.09-python-example",
    "chapter01.10-chart-migration-python-v1": "chapter01.10-python-example",
    "chapter01.10-chart-migration-v1": "chapter01.10-historical-chart-migration",
    # slightly-wrong recipe names -> real files
    "chapter05.07-longitudinal-patient-matching": "chapter05.07-longitudinal-patient-matching-name-changes",
    "chapter05.10-deceased-patient-resolution": "chapter05.10-deceased-patient-resolution-reconciliation",
    "chapter07.09-mortality-risk-scoring": "chapter07.09-mortality-risk-scoring-icu",
    "chapter09.07-radiology-ai-triage": "chapter09.07-radiology-ai-triage-multi-modality",
    "chapter10.10-multilingual-real-time-medical-interpretation": "chapter10.10-multilingual-realtime-medical-interpretation",
    "chapter03.10-outbreak-detection": "chapter03.10-epidemic-outbreak-detection",
    "chapter15.10-hospital-resource-allocation-under-uncertainty": "chapter15.10-hospital-resource-allocation-uncertainty",
}

# chapterNN-index -> chapterNN-preface, for every chapter that HAS a preface.
for ch in [f"{n:02d}" for n in range(1, 16)]:
    if ch == "12":
        continue  # no chapter12-preface yet (content gap)
    EXACT[f"chapter{ch}-index"] = f"chapter{ch}-preface"


def fix_text(text: str) -> tuple[str, int]:
    """Replace link targets inside ](target) and ](target#anchor)."""
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        target = m.group("t")
        anchor = m.group("a") or ""
        if target in EXACT:
            count += 1
            return f"]({EXACT[target]}{anchor})"
        return m.group(0)

    # Match markdown link target: ](target) or ](target#anchor)
    pattern = re.compile(r"\]\((?P<t>[^)#]+)(?P<a>#[^)]+)?\)")
    return pattern.sub(repl, text), count


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    touched = 0
    for f in sorted(glob.glob("chapter*.md")):
        text = Path(f).read_text(encoding="utf-8")
        new, n = fix_text(text)
        if n:
            total += n
            touched += 1
            print(f"{'FIX' if apply else 'would fix'} {n:3d} in {f}")
            if apply:
                Path(f).write_text(new, encoding="utf-8")
    print(f"\n{'Applied' if apply else 'Would apply'} {total} replacements across {touched} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
