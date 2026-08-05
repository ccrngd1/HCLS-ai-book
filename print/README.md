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

## KNOWN BLOCKER: fonts are not print-valid on the Linux host

`print.css` sets the body face to `Georgia, "Times New Roman", serif`. Neither
Georgia nor Times New Roman is installed on the cloud desktop, so Chrome
substitutes Nimbus Roman. Two consequences, both disqualifying for KDP:

1. **The page count is wrong.** Nimbus Roman is more compact than Georgia, so the
   interior renders at **229 pages** here versus the **268** recorded at Phase C
   close on a machine that had Georgia. Spine width is a function of page count,
   so do not compute a cover from a build made on this host.
2. **Fonts are not embedded.** The only `/BaseFont` in the rendered PDF is
   `DejaVuSansMono`. The body serif is not embedded at all. KDP requires all fonts
   embedded.

Pick one before generating the cover:

- **Render on the machine that has Georgia** (where the 268-page figure came from).
  Cheapest path to a valid interior; leaves the build non-reproducible.
- **Stop depending on a system font** (recommended). Add an openly-licensed serif
  as a repo asset and reference it with `@font-face` in `print.css`. Gelasio is
  metric-compatible with Georgia and OFL-licensed, so it should preserve pagination
  closely while guaranteeing embedding and making the build reproducible on any
  host. This changes the typeface slightly and needs a visual check plus a fresh
  page-count baseline.

Until one of those is done, treat `--pdf` output from this host as a layout smoke
test, not a print master.

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
