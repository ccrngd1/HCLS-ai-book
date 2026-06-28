# Print pipeline (Phase C) — flagship-15 6×9 PDF

Builds the curated **flagship-15** print edition as a derived artifact from the
canonical recipe sources. It **never edits the canonical `.md` files** — all
transforms run on a copy written to `print/build/` (gitignored).

Pipeline: `canonical Markdown → print-adapted Markdown → combined HTML → 6×9 PDF`

## Files
- `manifest.json` — the single source of truth: the 15 recipes, their print
  chapter numbers, titles, and `approved` flags, plus book metadata
  (title, author, copyright year, digital-edition URL). **Edit this** to flip a
  recipe to `approved: true` as you sign off on it, or to set the real
  digital-edition URL / author name.
- `build.py` — the deterministic, re-runnable build.
- `print.css` — 6×9 trade-paperback stylesheet (honored by headless-Chrome
  print via `preferCSSPageSize`).
- `build/` — output (gitignored): adapted `.md` per recipe, `book.md`,
  `book.html`, `book.pdf`, and `print-warnings.txt`.

## Usage
Run with a Python that has a Markdown engine (the md-to-html venv works):

```bash
PY="/…/projects/md-to-html/.venv/bin/python"
"$PY" print/build.py            # approved recipes only (default)
"$PY" print/build.py --all      # all 15 (unapproved/missing included)
"$PY" print/build.py --pdf      # also render book.pdf (needs puppeteer + Chrome)
```

PDF rendering needs puppeteer:
```bash
cd print/build && npm init -y && npm i puppeteer    # one-time, ~Chromium download
"$PY" print/build.py --pdf
```

## Transforms applied (plan_docs/physical-book-plan.md §2b)
1. **Strip the web nav footer** (`*← … →*`).
2. **Reframe `## Related Recipes`** → a digital-edition pointer. The original
   bullet list is preserved as an HTML comment (`PRINT-TODO`) so you can later
   hand-write a one-sentence concept summary.
3. **Inline `Recipe N.N` refs:** if `N.N` is a flagship → renumbered to
   `Chapter <print_chapter>`; if not → left as-is and reported in
   `print-warnings.txt` as `[PRINT-WARN]` for you to reword to a concept.
4. **Rewrite the architecture-companion callout** → points at the digital edition.
- Also strips the web-only `## Tags` chip section and collapses orphaned rules.

Front matter (title, copyright, preface, how-to-use) and back matter
(contents, "more recipes online") are generated from `manifest.json`.

## Still TODO (Phase C remainder)
- **Mermaid pre-render (§2c):** render ```mermaid blocks to SVG once and embed
  across HTML/EPUB/PDF. The approved flagship main files are currently ASCII
  diagrams (0 Mermaid), so this is low-impact for the subset today but required
  before the heavy recipes (10.7, 11.6) and EPUB.
- **QR code** for the digital-edition URL on the front matter.
- **Index** generation (back matter currently lists contents only).
- Review each recipe's `[PRINT-WARN]` prose refs and reword to concepts.
