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

The build needs a Markdown engine, and `--pdf` additionally needs Node plus a
Chrome that Puppeteer can drive. Both work on the Linux cloud desktop with the
setup below. There is no dependency on the `md-to-html` virtualenv any more; that
venv is currently broken anyway (its `bin/python` symlinks were flattened to
0-byte files), so do not rely on it.

### One-time setup

```bash
# Markdown engines. markdown-it-py matches the site build and is the default.
# Pin <4 because 4.x requires Python 3.10+ and the system python here is 3.9.
python3 -m pip install --user "markdown-it-py<4" "mdit-py-plugins<0.5" pygments
python3 -m pip install --user markdown          # optional alternate engine

# Chrome for Puppeteer (~150 MB, once). Puppeteer lives in print/build/node_modules.
export PATH="$HOME/.local/share/kiro-cli:$PATH"   # bundled node v22
cd print/build && node -e "
const {install,resolveBuildId,detectBrowserPlatform,Browser}=require('@puppeteer/browsers');
(async()=>{const p=detectBrowserPlatform();
const b=await resolveBuildId(Browser.CHROME,p,'stable');
const r=await install({browser:Browser.CHROME,buildId:b,cacheDir:process.env.HOME+'/.cache/puppeteer'});
console.log(r.executablePath);})();"
```

### Building

```bash
export PATH="$HOME/.local/share/kiro-cli:$PATH"
export PUPPETEER_EXECUTABLE_PATH=$(ls -d ~/.cache/puppeteer/chrome/linux-*/chrome-linux64/chrome | head -1)

python3 print/build.py                    # approved recipes, HTML only
python3 print/build.py --all              # include unapproved/missing
python3 print/build.py --pdf              # also render book.pdf (two-pass TOC)
python3 print/build.py --engine auto      # first-available engine (old behaviour)
```

`PUPPETEER_EXECUTABLE_PATH` is required because the installed Chrome (151) is
newer than the exact build Puppeteer 25.2.1 pins (150), and Puppeteer refuses to
fall back on its own.

### Engine choice affects pagination

`--engine` defaults to `markdown-it-py` to match the md-to-html site generator.
Different engines emit different HTML, which changes pagination, which changes the
page count and therefore the cover spine width. Keep it pinned rather than relying
on whatever happens to be installed. (Measured: python-markdown and markdown-it-py
both produce 229 pages here, so the engine is not the cause of the discrepancy
described next.)

## Fonts are embedded (resolved 2026-08-05)

`print.css` embeds its own faces via `@font-face`, so the interior renders
identically on any host and every glyph is embedded in the PDF, which KDP
requires. Assets live in `print/assets/fonts/`:

- **Gelasio** (body serif) in regular, italic, bold, bold-italic. Metric-compatible
  with Georgia and licensed under the SIL Open Font License (`OFL.txt`).
- **DejaVu Sans Mono** (code) in regular, bold, oblique (`DejaVu-LICENSE.txt`).

Georgia remains only as a CSS fallback after Gelasio. **Do not remove Gelasio and
fall back to a bare `Georgia` reference.** Georgia is not installed on the Linux
build host; Chrome silently substitutes a more compact serif, the body font ends
up unembedded, and the page count shifts without warning. That failure cost 39
pages of drift (229 rendered versus 268 recorded) before it was caught.

Verify after any font or CSS change:

```bash
python3 - <<'EOF'
import re
d=open("print/build/book.pdf","rb").read()
print(sorted(set(m.group(1).decode() for m in re.finditer(rb'/BaseFont\s*/([\w+#,.-]+)', d))))
print("embedded programs:", len(re.findall(rb'/FontFile2', d)))
print("pages:", len(re.findall(rb'/Type\s*/Page[^s]', d)))
EOF
```

Expect Gelasio and DejaVuSansMono subsets, and a non-zero `/FontFile2` count.

## Appendix B is generated from the recipe tags

`print/tag_index.py` builds Appendix B on every run by reading the `## Tags`
section of all 152 recipes. It replaced a hand-curated `index-terms.json`, which
could drift from the text and which pointed at recipe *numbers* only, leaving a
reader of the printed book with "5.5, 5.8, 5.9" and no page to turn to.

Each entry now gives the **page** for recipes printed in this book, plus the
recipe numbers covering the same topic in the digital edition.

Two presentation rules, both about the index entry rather than the underlying
tags, which stay complete on every recipe:

- Tags carried by 40% or more of recipes are named once as pervasive and not
  enumerated. A tag on most recipes cannot help anyone find anything. Currently:
  HIPAA, Amazon DynamoDB, Amazon SageMaker, AWS Lambda.
- The digital-edition list is capped at 12 numbers, then "and N more".

Display names come from a `DISPLAY` map in `tag_index.py`; add an entry there when
a new tag should not simply be its slug title-cased (for example `s3` renders as
"Amazon S3").

`index-terms.json` is retained as a fallback: if `tag_index.py` raises, the build
prints a warning and falls back to the curated index rather than shipping a book
with no index.

Page numbers come from `build/toc-pagemap.json`, produced by the two-pass render.
This is stable because the appendices sit at the back, so their own length never
moves the recipe pages they cite. Verify after a build:

```bash
python3 print/tag_index.py --stats     # recipe/tag/pagemap counts
python3 print/tag_index.py | head -20  # inspect the markdown
```

## Current interior: 254 pages

Rendered with embedded fonts and `--engine markdown-it-py`, 6.00 x 9.00in trim,
0 reference warnings. This supersedes the 268-page figure recorded at Phase C
close, which was produced with a substituted system font on another machine and
is not reproducible.

Spine width at 254 pages: **0.6350in** on cream 60# stock, **0.5653in** on white
50#. Confirm against KDP's calculator for the stock you select, and note the count
is currently odd, so add a trailing blank if you want the interior to end on a
verso.

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

Front matter (title, copyright, preface, how-to-use, digital-edition QR) and
back matter (contents, Appendix A recipe catalog, Appendix B topic/service
index, "more recipes online") are generated from `manifest.json` plus
`appendix-catalog.json` and `index-terms.json`.

## Phase C status: COMPLETE
Delivered: the §2b transforms, generated front/back matter, the digital-edition
QR code, Appendix A (all 152 recipes), Appendix B (tag-derived topic/service
index), and TOC page numbers via the two-pass render. Current PDF: 268 pages,
0 cross-reference warnings (all `[PRINT-WARN]` prose refs reworded to concepts).

Mermaid pre-render (§2c) was assessed and is **not needed for print**: the 15
flagship main files carry no Mermaid blocks, and the digital edition renders
Mermaid client-side. It remains a prerequisite for EPUB.

Next: Phase D (KDP publishing) — see `plan_docs/physical-book-plan.md` §6 and
`print/kdp-metadata.md`.

## TOC page numbers (two-pass)

`build.py --pdf` renders the PDF, extracts each recipe's printed page from that
render (`extract-toc-pages.js`, via `pdfjs-dist` installed in `build/node_modules`),
writes `build/toc-pagemap.json`, then rebuilds and re-renders so the Table of
Contents shows real page numbers with dot leaders. If Node or `pdfjs-dist` is
unavailable, the step is skipped and the TOC renders without page numbers (no error).
One-time setup: `cd build && npm i pdfjs-dist`.
