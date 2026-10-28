# Backlog

The one place to start when asking "what is left to do?" It points to the files that
track each kind of work and holds the general items that have no other home.

**Rule:** if an item has a row or entry in one of the sources below, that source is
authoritative and this file only points to it. Update status there, not here. Items
listed in full here are ones no other file tracks.

_Last updated: 2026-10-07_

---

## Where work is tracked

| Source | What it holds | In git? |
|--------|---------------|---------|
| [`reviews/REVIEW-TRACKER.md`](REVIEW-TRACKER.md) | Reviewer findings and author tasks (`A-`, `AR-`). Open items are listed in the generated digest at the top (`python3 tracker_digest.py`). | Yes |
| [`plan_docs/physical-book-plan.md`](../plan_docs/physical-book-plan.md) | Print phases A to E, the flagship-15, the buy-versus-build taxonomy (§6c), the tightening backlog (§5). | No (gitignored) |
| `chapterNN.RR-todo.md` (152 files, repo root) | Per-recipe findings; `[NEEDS HUMAN]` marks deferrals that need an author decision or external check. `grep -l 'NEEDS HUMAN' chapter*-todo.md` | No (gitignored) |
| `reviews/chapterNN.RR-{expert,code}-review.md`, `reviews/*-edit-status.md` | Per-recipe persona reviews that fed the todo files. | No (gitignored) |
| `reviews/peers/ext-review-*.md` | Raw external reviewer feedback, before triage into the tracker. | No (gitignored) |
| `tasks.json`, `specs/` | Automation task queue and per-task specs. | No (gitignored) |
| [`print/README.md`](../print/README.md), [`print/kdp-metadata.md`](../print/kdp-metadata.md) | Print build, validation, and KDP listing copy. | Yes |

---

## 1. Print release (blocks KDP publish)

Roughly in order. Content must be frozen before the TOC step.

- [ ] **Recipe 1.1 still says OCR "goes back to the 1970s"** (`chapter01.01-insurance-card-scanning.md:30`, print-bound). Tracker row V-1.7b is marked DONE, but the correction landed only in `chapter01-preface.md`, which is digital-only. Fix the recipe and reopen or annotate V-1.7b.
- [ ] **KDP description promises "runnable examples"** (`print/kdp-metadata.md`). This contradicts the README, which calls the Python companions illustrative sketches that are not a deployable asset. Reword before the listing goes live.
- [ ] Close the open print-bound tracker rows: V-1.7h, V-3.10, V-3.11, V-11.3, V-11.4, VH-2, VH-3, VH-4.
- [ ] Wait for Veronica (VH) and Tory (T) to finish their reviews. Then triage Tory's batched per-recipe notes, which are described in tracker §17 but not yet logged as rows.
- [ ] Freeze content, then regenerate TOC page numbers: **A-5**.
- [ ] Decide paper stock (kdp-metadata suggests white) and add a trailing blank if the final page count is odd.
- [ ] Produce the full-wrap paperback cover PDF (back, spine, front) from KDP's cover template at the final page count. `BookCoverV1.png` is the front only.
- [ ] Optional: pad the ebook cover to KDP's ideal 1.6:1 (currently 1696x2528, about 1.49:1). Last open part of **A-3**.
- [ ] Set the list price with KDP's royalty calculator.
- [ ] Order a physical proof; do the author final read (this also covers the About the Author orphan from A-2).
- [ ] Publish.

Already clear: the plan's "clear main-file `[NEEDS HUMAN]` items before ordering the proof" gate. As of 2026-10-07, all remaining flagship deferrals are in architecture companions (digital-only).

---

## 2. Digital edition: per-recipe rollouts (137 non-flagship recipes)

The flagship 15 have all of these. A-1 already requires reviewing each recipe in person, so the
other rollouts are cheapest done in the same per-recipe pass.

| Item | Progress | Tracked in |
|------|----------|------------|
| Restore the Honest Take | 0 of 137 | **A-1** (`python3 honest_takes.py --status`) |
| Buy-versus-build verdict as the Honest Take lead-in | 15 of 152 | plan §6c only (no tracker row) |
| "As Seen In Production" section | 15 of 152 | **A-7** |
| `User:` persona line | 15 of 152 | **AN-5** |
| Resolve `[NEEDS HUMAN]` deferrals | 79 todo files still carry them | `chapter*-todo.md` |
| Section-divider (`---`) rules | 22 of 152 (all 15 print recipes) | `python3 check_rules.py --all`; rules in RECIPE-GUIDE. Fix each recipe after restoring its Honest Take, since `--fix` moves the rule above that section |

---

## 3. Digital edition: other content work

- [ ] Dead-link sweep across the non-flagship companions: **AR-5**. FDA links need manual browser checks: **AR-6**.
- [ ] Phase 2 technical and AWS-accuracy review of the flagship architecture companions: 1 of 15 done (1.1, under AR-7). No tracker row for the other 14.
- [ ] Decide on the AR-7 hardening recommendations for 1.1 (S3 Block Public Access and versioning, PHI retention, Textract backoff, and others listed in the row).
- [ ] Finish the last automation task: `ch08-r06-findings` (recipe 8.6, SDOH extraction), still pending in `tasks.json`.
- [ ] Phase E tightening. Measured 2026-10-07: 22 main recipes are at or above 7,000 words, led by 11.9 (11,448), 11.8, 11.7, 11.10, 11.4. The 41-row table in plan §5 uses older counts and is stale.
- [ ] Deferred, by author decision: quantify stakes where a Problem section is thin (**AN-7**).
- [ ] Optional: convert the ASCII diagrams in companions to Mermaid (plan §2c). Pre-rendering only matters if companions are ever added to the EPUB.

---

## 4. Tooling and documentation

- [ ] **Internal authoring guides are published.** `docs/RECIPE-GUIDE.html` and `docs/STYLE-GUIDE.html` are rendered and committed to the public site (not linked from the sidebar, but reachable by URL). STYLE-GUIDE names the private voice-file setup. This is the same class of problem as R-8 (`SUMMARY.md`). Decide whether to exclude both from the md-to-html build.
- [ ] **RECIPE-GUIDE.md has drifted.** It does not document the `User:` line, the "As Seen In Production" section, the buy-versus-build lead-in, or the PHI callout. (Its stale main-recipe Navigation footer instruction was corrected on 2026-10-07, alongside the new section-divider rules.)
- [ ] `STYLE-GUIDE.md` and `RECIPE-GUIDE.md` both say to read `~/.openclaw/global/VOICE.md`, which is not on the current cloud desktop.
- [ ] **R-1 gate blind spot: the paragraph after every code block is never checked.** In `check_abbreviations.prose_of()`, the indented-code rule `^\s{4,}\S.*$` lets `\s` match newlines. Once a code fence has been blanked to whitespace, the rule runs across it and also blanks the first line (in practice, the whole paragraph) that follows. `print/acronym_sweep.py` reuses `prose_of`, so it has the same blind spot. Found 2026-10-07 when converting the 3.1 diagram exposed a bare EDI. Fix: `^[ \t]{4,}\S.*$`. Expect new R-1 findings corpus-wide afterwards, mostly in architecture companions (pseudocode blocks).
- [ ] Candidate tooling fix: make `print/acronym_sweep.py` require the expansion at or before the first occurrence (the blind spot behind VH-4).
- [ ] EPUB: the `epub:type` (frontmatter, bodymatter, backmatter) that `render_epub` puts on each `<body>` never ships, because EbookLib rebuilds `<body>` and drops its attributes (the same mechanism that was dropping the CSS). ACE still passes. Fix by moving the attribute onto a wrapper `<section>`.
- [ ] The md-to-html virtualenv is broken (`bin/python` symlinks flattened to 0-byte files; see print/README). Rebuild it with **pinned** renderer versions: the published `docs/` was rendered with Pygments 2.7.4, markdown-it-py 3.0.0 and mdit-py-plugins 0.4.2 (needs Python 3.10+; `~/.local/bin/python3.12` works). Unpinned current versions re-render every page with a code block (about 300 files of whitespace and quote-escaping drift). md-to-html's `pyproject.toml` only sets lower bounds, so pin these there too.

---

## 5. Housekeeping

- [ ] `categories/` is tracked but superseded: **R-9**.
- [ ] `.dup-backup-20260604/` holds 7 stale duplicates (gitignored). Delete once confirmed redundant.
- [ ] Most planning and review data is gitignored (`plan_docs/`, `planning/`, `specs/`, `reviews/*` except the tracker and this file, `chapter*-todo.md`, `tasks.json`), so it has no history or off-machine backup. Confirm that is intended.
- [ ] Monty's peer review (`reviews/peers/ext-review-monty.md`, positive only, no findings) is not listed in the tracker's Reviewers table.
