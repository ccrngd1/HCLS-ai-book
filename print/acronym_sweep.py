#!/usr/bin/env python3
"""AN-6: per-section acronym sweep over the printed book.

Why this exists, and how it differs from R-1 (check_abbreviations.py):

  * R-1 governs only terms listed in abbreviations.json. An acronym absent from
    that vocabulary (C-CDA was the proof) is invisible to R-1 and can appear cold.
  * Each printed recipe is meant to stand alone: a reader may open any chapter
    first. So the unit is the SECTION, not the book. An acronym expanded in one
    chapter but used bare on its first appearance in another chapter is a defect,
    because the second chapter is no longer self-contained. A book-order sweep
    would wrongly pass that; this sweep keys off first use WITHIN each section.

Sections are the top-level (`# `) divisions of print/build/book.md: each
front-matter page, each `# Chapter N:` recipe, and each appendix.

Reuses check_abbreviations.prose_of so code fences, inline code, link targets,
HTML comments, and table rows are excluded identically to R-1.

  python3 print/acronym_sweep.py           # full report
  python3 print/acronym_sweep.py --unknown # only the actionable unknown list
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOOK = os.path.join(HERE, "build", "book.md")

# Load check_abbreviations from the repo root for prose_of + the vocabulary.
_spec = importlib.util.spec_from_file_location(
    "check_abbreviations", os.path.join(ROOT, "check_abbreviations.py"))
_ca = importlib.util.module_from_spec(_spec)
_cwd = os.getcwd()
os.chdir(ROOT)  # DATA path in check_abbreviations is relative
try:
    _spec.loader.exec_module(_ca)
finally:
    os.chdir(_cwd)

# A candidate acronym: a word token carrying at least two uppercase letters
# (so ALLCAPS like PHI, caps+digit like HTI-1, hyphenated like C-CDA, and
# camel product names like RxNorm are caught; ordinary Titlecase words are not).
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")


def known_sets() -> tuple[set[str], dict[str, str]]:
    """(all governed tokens across every group, must-expand token -> canonical form)."""
    raw = json.loads(open(os.path.join(ROOT, "abbreviations.json"), encoding="utf-8").read())
    known: set[str] = set()
    must: dict[str, str] = {}
    for group, body in raw.items():
        if group.startswith("_") or not isinstance(body, dict):
            continue
        for key, val in body.items():
            if key.startswith("_") or key == "terms":
                continue
            known.add(key)
            if isinstance(val, dict) and val.get("expand") and val.get("form"):
                must[key] = val["form"]
    return known, must


def sections(prose: str) -> list[tuple[str, int, int]]:
    """Top-level (# ) divisions: (title, start, end) offsets into prose."""
    heads = [(m.start(), m.group(1).strip())
             for m in re.finditer(r"^# (.+)$", prose, re.M)]
    out = []
    for i, (start, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(prose)
        out.append((title, start, end))
    return out


def upper_count(tok: str) -> int:
    return sum(1 for c in tok if c.isupper())


# Sections that are generated reference matter, not standalone recipes. Acronyms
# whose only appearances are here are index/catalog/TOC entries, which behave like
# the tables R-1 already exempts, not prose a reader learns a definition from.
GENERATED = {
    "The Healthcare AI/ML Cookbook", "About the Author", "Contents",
    "Appendix A: The Complete Recipe Catalog", "Appendix B: Topic and Service Index",
}
# Two-letter/roman/unit tokens that are not abbreviations needing expansion.
STOP = {
    "II", "III", "IV", "OF", "BY", "OK", "IT", "AM", "PM", "US", "UK", "OR", "ID",
    "ER", "EM", "PD", "PK", "EF", "CT", "RN", "RX", "AB", "BS",
}

# Clinical, lab, condition, gene, drug-class, and vignette-PII shorthand. Left
# unexpanded by author ruling: a clinician reader knows these, and the patient
# scenarios they appear in are illustrative, not clinical reference.
CLINICAL = {
    "ACE", "ACP", "ADL", "AMI", "BNP", "CABG", "CBC", "CCU", "CGM", "CHF", "CKD",
    "COPD", "COW", "CYP2C19", "CYP2C9", "CYP3A4", "DME", "DNR", "DOB", "DOS", "DR",
    "ECG", "FEV1", "GLP-1", "HEART", "HMG-CoA", "HOSPITAL", "HPI", "INR", "IRMA",
    "LACE", "LUE", "MAO", "MAP", "MBR", "MI", "NPDR", "NYHA", "OCT", "PACU", "PCP",
    "PDR", "PHQ-9", "ROS", "SOAP", "SOFA", "SSN", "UTI", "WBC", "ZIP", "BIN", "PCN",
}
# Proper nouns: organizations, standards bodies, products, tools, file formats,
# and algorithm names. Not abbreviations to expand.
WELLKNOWN = {
    "JAMA", "IBM", "CDC", "NHS", "MHRA", "RAND", "AHRQ", "AHIMA", "ECRI", "NPSG",
    "CPLEX", "DBSCAN", "XGBSE", "REST", "XML", "HTML", "PDF", "IDx-DR", "AEYE",
    "PMID", "DOI", "TF-IDF", "SMOG", "MED-RT", "NDF-RT", "OR-Tools", "CP-SAT", "CP",
    "K-Means", "K-Medoids", "Q-Learning", "Q-Iteration", "HCUP", "KMS",
    # Common business/technical terms and citation/rule proper-names (author ruling):
    "CFO", "ROI", "QA", "SLA", "UX", "PTO", "CFR", "HTI-1",
}
# ALLCAPS English words and code-label fragments caught by the token regex.
NOTACRONYM = {"CAUSES", "INDUCES", "INHIBITS", "SUBSTRATE", "SUPPORTED", "E08-E13"}
# House-universal terms: the book's core vocabulary. Expanding on every recipe's
# first use would be absurd ("AWS" opens nearly every recipe). Treated like the
# context-dependent terms R-1 already exempts (LLM, API, EHR).
HOUSE = {"AI", "ML", "AWS", "VEGF", "ST", "FTE"}

EXEMPT = STOP | CLINICAL | WELLKNOWN | NOTACRONYM | HOUSE


def classify(tok: str, known: set[str]) -> str:
    """Bucket a candidate token."""
    if tok in known:
        return "governed"
    if tok in EXEMPT:
        return "exempt"                # stop-word, clinical, well-known, or non-acronym
    if "-" in tok:
        parts = tok.split("-")
        if any(p in known or p in EXEMPT for p in parts):
            return "derived"           # LLM-based, AWS-specific, KMS-encrypted, missing-SSN
        if all(re.fullmatch(r"[A-Z][a-z]+|[a-z]+|to|and|of", p) for p in parts):
            return "titlecompound"     # e.g. After-Visit, Speech-to-Text
        # else: hyphenated with an embedded acronym part (HTI-1, GLP-1)
        return "acronym"
    if re.fullmatch(r"[A-Z0-9]{2,}", tok):
        return "acronym"               # pure ALLCAPS (+digits): the real class
    if re.search(r"[a-z]", tok):
        return "camel"                 # DynamoDB, eGFR, XGBoost: proper/clinical
    return "acronym"


def main() -> None:
    only_unknown = "--unknown" in sys.argv
    if not os.path.exists(BOOK):
        sys.exit(f"no {BOOK}; build the print PDF first")
    raw = open(BOOK, encoding="utf-8").read()
    prose = _ca.prose_of(raw)  # non-prose blanked, offsets preserved 1:1 with raw
    known, must = known_sets()

    # Section boundaries come from raw: prose_of blanks ATX headings (a heading
    # occurrence must not count as a first use), so headings are invisible in prose.
    # Scope: recipes only (# Chapter N: ...). Author ruling excludes front matter,
    # appendices, TOC, and the governance/PHI pages from the standalone rule.
    secs = [(t, s, e) for (t, s, e) in sections(raw) if re.match(r"Chapter \d+:", t)]
    line_of = lambda off: raw.count("\n", 0, off) + 1

    # token -> list of occurrences (one per section, at its first use there)
    unknown: dict[str, list] = {}
    known_unexpanded: dict[str, list] = {}
    known_seen: set[str] = set()

    for title, s, e in secs:
        seg = prose[s:e]
        first_at: dict[str, int] = {}
        for m in TOKEN.finditer(seg):
            tok = m.group(0)
            if upper_count(tok) < 2:
                continue
            if tok not in first_at:
                first_at[tok] = m.start()
        for tok, off in first_at.items():
            abs_off = s + off
            end = abs_off + len(tok)
            ln = line_of(abs_off)
            snip = re.sub(r"\s+", " ", raw[max(0, abs_off - 45):abs_off + 45]).strip()
            gen = title in GENERATED
            # Defined inline if the token sits inside its own expansion, either
            # "Expansion (TOK)" or "TOK (Expansion)".
            before = abs_off > 0 and raw[abs_off - 1] == "("
            after = re.match(r"\s*\([A-Za-z]", raw[end:end + 40]) is not None
            inline = before or after
            if tok in known:
                known_seen.add(tok)
                if tok in must:
                    form = must[tok]
                    fpos = seg.find(form)
                    if fpos == -1 or not (fpos <= off <= fpos + len(form)):
                        known_unexpanded.setdefault(tok, []).append((title, ln, gen))
            else:
                unknown.setdefault(tok, []).append(
                    {"title": title, "ln": ln, "snip": snip, "gen": gen, "inline": inline})

    # Bucket every unknown token.
    buckets: dict[str, list[str]] = {}
    for tok in unknown:
        buckets.setdefault(classify(tok, known), []).append(tok)

    # Actionable defect: an all-caps-class acronym with a first use in a RECIPE
    # BODY (not generated matter) that is NOT defined inline there.
    actionable = []
    for tok in buckets.get("acronym", []):
        body_bare = [o for o in unknown[tok] if not o["gen"] and not o["inline"]]
        if body_bare:
            actionable.append((tok, body_bare))

    if not only_unknown:
        print(f"Sections scanned: {len(secs)}  |  raw multi-cap tokens: {len(unknown)} unknown, "
              f"{len(known_seen)} governed")
        print("Buckets (unknown tokens):")
        for b in ("acronym", "camel", "derived", "titlecompound", "stop"):
            print(f"    {b:14} {len(buckets.get(b, []))}")
        print(f"\nGoverned terms bare at first use (mostly generated matter): "
              f"{len(known_unexpanded)}")
        gen_only = sum(1 for t in known_unexpanded if all(g for _, _, g in known_unexpanded[t]))
        print(f"    of those, ONLY in generated matter (index/catalog/TOC): {gen_only}")
        print()

    print(f"ACTIONABLE: unknown all-caps acronyms bare in a recipe body ({len(actionable)}):")
    for tok, hits in sorted(actionable):
        secs_ = ", ".join(h["title"].split(":")[0] for h in hits)
        print(f"  {tok:16} [{secs_}]")
        print(f"        L{hits[0]['ln']}: ...{hits[0]['snip']}...")


if __name__ == "__main__":
    main()
