# Recipe Split Migration: 2-File to 3-File Structure

**Status:** Approved, in execution
**Goal:** Reduce "the book" from ~7,000 pages to a readable core by separating each recipe's vendor-agnostic story/concepts (Part 1) from its AWS implementation/pseudocode (Part 2), which moves to a `-architecture` companion. Python companion is unchanged.

## Background and rationale

The cookbook is ~2.8M words / ~7,000 pages. Measured breakdown: Part 1 (story + concepts + general architecture) is only ~20% of the bulk; Part 2 (AWS + pseudocode + wrap-up) is ~37%, and the Python examples are ~41%. Separating Part 2 into a companion shrinks the readable "book" (Part 1 + Honest Take + Related + Tags + prefaces) to ~772K words. Each recipe's readable portion becomes ~5,000 words (25-34 min read), an appropriate dip-in unit for a cookbook.

The 3.1 pilot (done purely by the deterministic `split_recipe.py`, no LLM) was approved as the target quality bar.

## Three-file model

| File | Sections | Audience |
| --- | --- | --- |
| `chapterNN.RR-<slug>.md` (main, "the book") | The Problem, The Technology, General Architecture Pattern, The Honest Take, Related Recipes, Tags, nav. Ends General Architecture with a callout linking to the architecture companion. | exec / PM / architect-curious |
| `chapterNN.RR-architecture.md` (companion) | The AWS Implementation (Why These Services, diagram, prerequisites, ingredients, pseudocode walkthrough, expected results), Why This Isn't Production-Ready, Variations and Extensions, Additional Resources, Estimated Implementation Time. Backlink header + footer to main + python. | architect / implementer |
| `chapterNN.RR-python-example.md` (unchanged) | Setup, config, per-step code, full pipeline, gap to production | engineer |

The Honest Take stays on the main recipe (explicit decision).

## Key engineering decisions

1. **The content move is deterministic (`split_recipe.py`), never LLM-driven.** Moving ~10K words per recipe across 150 recipes via an LLM risks truncation/hallucination/content loss. The script is byte-exact and reconciles word counts. The 3.1 pilot validated this produces excellent output with zero LLM involvement.
2. **Ralph's role is QA/polish + edge cases, not the move.** A per-recipe `TechEditor` `persona_review` confirms each file reads standalone and fixes transition seams (e.g., a Honest Take dangling a reference to moved AWS content). Full-review on all recipes was chosen over spot-check.
3. **Sequence: bulk-split-first, then polish.** Because ralph runs the persona before validation checks, the split is done as a deterministic pre-step (bulk, instant) so the polish persona always operates on already-split files. The split is NOT done inside each ralph task.
4. **`_Sidebar.md` is regenerated in one pass, outside the parallel tasks.** It is a single shared file; concurrent per-task edits would cause commit-attribution conflicts. Sidebar regeneration is Phase 2.

## Exclusions / edge cases

- `chapter01-executive-summary.md` — not a recipe; excluded from the split.
- `chapter03.01-*` — already split (pilot).
- `chapter11.10-clinical-trial-recruitment-conversationalist.md` — no clean AWS boundary; bespoke manual task.
- 150 of 153 recipes split cleanly on the `## The AWS Implementation` / `## Why These Services` boundary.

## Governance changes (Phase 0)

| Artifact | Change |
| --- | --- |
| `RECIPE-GUIDE.md` | Redefine as three files; add architecture-file section; update file-naming table and sidebar rules; relocate the python callout, add the main->architecture callout. |
| `personas/tech_writer.yaml` | Rewrite the structure block: main = Part 1 + Honest Take/Related/Tags; architecture = Part 2. |
| `personas/tech_editor.yaml` | Split pass conditions by file (main vs architecture). |
| `personas/planner.yaml` | Add architecture stage (6-stage chain); python depends on architecture; drop the dead chapter-index task; bump stage cap to 6. |
| Validation specs | New 6-stage templates for future recipes only; existing specs untouched (content already passed). |
| `split_recipe.py`, `md-to-html` | Exclude list for executive-summary; build dup-slug guard already knows `-architecture`. |

## Going-forward 6-stage chain (new recipes)

draft (main, Part1) -> architecture (Part2) -> python (depends architecture) -> code-review (depends python) ; expert-review (depends architecture) ; edit (main + architecture, depends code-review + expert-review).

## Execution phases

- **Phase 0:** governance + helper scripts + this doc.
- **Phase 1a:** deterministic bulk split of the 150 clean recipes; commit.
- **Phase 1b:** parallel ralph polish tasks (one TechEditor `persona_review` per recipe); bespoke task for ch11.10.
- **Phase 2:** regenerate `_Sidebar.md`, cross-link sweep, rebuild HTML, verify warnings == baseline.

## Helper scripts

- `split_recipe.py` — deterministic Part1/Part2 splitter (idempotent; no-op on already-split files).
- `check_split.py` — structural validation: boundary absent from main, present in architecture, cross-links present.
- `regen_sidebar.py` — single-pass `_Sidebar.md` regenerator that inserts `-architecture` entries.
