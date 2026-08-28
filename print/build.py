#!/usr/bin/env python3
"""
Print pipeline for the Healthcare AI/ML Cookbook flagship-15 (Phase C).

canonical Markdown  ->  print-adapted Markdown  ->  combined HTML  ->  6x9 PDF

Design contract (per plan_docs/physical-book-plan.md section 2b):
  * NEVER writes back to the canonical recipe files. All transforms run on a
    copy in print/build/.
  * Deterministic and re-runnable: same inputs -> identical outputs.
  * Manifest-driven: print/manifest.json is the single source of truth for
    which recipes are in the print subset and what print chapter each maps to.
    That flagship set drives the renumber-vs-flag decision for cross-references.

Transforms applied to each recipe (section 2b):
  1. Strip the web nav footer ( *<- ... -> * line ).
  2. Reframe the "## Related Recipes" section into a pointer to the digital
     edition (the original list is preserved as an HTML comment for the author
     to hand-craft a concept sentence later).
  3. Rewrite inline `Recipe N.N` mentions:
       - if N.N is a flagship  -> renumber to "Chapter <print_chapter>"
       - if N.N is NOT flagship -> leave text untouched, emit a [PRINT-WARN]
         so the author can reword it to describe the concept.
  4. Rewrite the architecture-companion callout to point at the digital edition.
  Plus: strip the web-only "## Tags" chip section and collapse orphaned rules.

Usage:
  python3 build.py                 # build only author-approved recipes (default)
  python3 build.py --all           # build all 15 (missing/unapproved included)
  python3 build.py --pdf           # also render the 6x9 PDF (needs puppeteer/Chrome)
  python3 build.py --out DIR       # override output dir (default: print/build)

Needs a Markdown engine: pip install --user "markdown-it-py<4" (preferred, matches
the site build) or markdown. See print/README.md for the full setup, including
Chrome for --pdf and the known font blocker. Example:
  python3 print/build.py --pdf
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOOK_ROOT = os.path.dirname(HERE)


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def load_manifest() -> dict:
    with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def resolve_source(recipe: str) -> str | None:
    """Find the canonical *main* recipe file for a recipe id like '10.7'.

    Excludes the -architecture / -python-example / -todo companions.
    """
    ch, rr = recipe.split(".")
    prefix = f"chapter{int(ch):02d}.{int(rr):02d}-"
    cands = [
        p for p in glob.glob(os.path.join(BOOK_ROOT, prefix + "*.md"))
        if not p.endswith(("-architecture.md", "-python-example.md", "-todo.md"))
    ]
    return cands[0] if cands else None


# --------------------------------------------------------------------------- #
# Transforms (section 2b)
# --------------------------------------------------------------------------- #
# Nav footers appear in at least five hand-written shapes: italic-wrapped
# (*<- ... ->*), a table row (| [<- ...] | ... |), bare links, and a
# "**Navigation:**" label. Matching only the italic form left 19 footers in the
# book, one of which printed as live blue links on an external page. Key on the
# left arrow plus a link to a chapter page, which no prose or diagram line has
# (verified zero matches inside fenced code blocks across all 152 recipes).
NAV_FOOTER_RE = re.compile(r"(?m)^.*\u2190.*\]\(chapter[^\n]*$")
TAGS_RE = re.compile(r"(?ms)\n?##\s+Tags\s*\n.*?(?=\n##\s|\Z)")
RELATED_RE = re.compile(r"(?ms)^(##\s+Related Recipes)\s*\n(.*?)(?=\n##\s|\Z)")
ARCH_CALLOUT_RE = re.compile(
    r"(?m)^>\s*\*\*The AWS build lives in a companion page\.\*\*.*$"
)
RECIPE_REF_RE = re.compile(r"Recipe\s+(\d+)\.(\d+)")
MULTI_RULE_RE = re.compile(r"(?ms)(?:^\s*-{3,}\s*\n\s*){2,}")


REL_LINK_RE = re.compile(r"\]\((chapter[0-9][^)\s]*)\)")


def absolutise_links(md: str, url: str) -> tuple[str, int]:
    """Point any surviving relative recipe link at the digital edition.

    Relative markdown links render as file:// annotations in the PDF, which leaks
    the local build path (username, directory layout) into a document handed to
    customers. Belt-and-braces behind the nav-footer strip.
    """
    base = url.rstrip("/")
    if not base:
        return md, 0
    return REL_LINK_RE.subn(lambda m: f"]({base}/{m.group(1)}.html)", md)


def strip_nav_footer(md: str) -> tuple[str, int]:
    md2, n = NAV_FOOTER_RE.subn("", md)
    return md2, n


def strip_tags(md: str) -> tuple[str, int]:
    md2, n = TAGS_RE.subn("", md)
    return md2, n


RELATED_PLACEHOLDER = "@@RELATED_POINTER@@"


def split_related(md: str) -> tuple[str, str | None]:
    """Replace the Related Recipes section with a placeholder; return original body.

    Done first so the ref-rewriter never sees the (about-to-be-removed) list or
    the preserved-as-comment original. The placeholder has no digits, so it is
    inert to the ref scan; the real pointer (with the commented original) is
    reattached afterwards.
    """
    m = RELATED_RE.search(md)
    if not m:
        return md, None
    original = m.group(2).strip()
    md2 = md[:m.start()] + f"## Related Recipes\n\n{RELATED_PLACEHOLDER}\n" + md[m.end():]
    return md2, original


def build_related_pointer(original: str, recipe_url: str, base_url: str) -> str:
    commented = "\n".join("     " + ln for ln in original.splitlines())
    return (
        "In the full digital cookbook, this recipe connects to related "
        "patterns across the library: upstream inputs, downstream "
        "consumers, and adjacent techniques in other chapters. "
        f"Read this recipe with its full set of cross-links in the digital "
        f"edition at <{recipe_url}>, or browse the complete library at "
        f"<{base_url}>.\n\n"
        "<!-- PRINT-TODO: optionally replace the generic pointer above with "
        "a one-sentence concept summary. Original web links preserved below:\n"
        f"{commented}\n-->"
    )


def rewrite_arch_callout(md: str, arch_url: str) -> tuple[str, int]:
    replacement = (
        "> **The implementation lives in the digital edition.** This printed "
        "recipe covers the problem, the underlying technology, and the "
        "cloud-agnostic architecture. For one concrete build of it, on AWS, with the architecture "
        "diagram, prerequisites, and step-by-step pseudocode, see the companion "
        f"page at <{arch_url}>."
    )
    return ARCH_CALLOUT_RE.subn(replacement, md)


def rewrite_recipe_refs(
    md: str, flagship_map: dict[str, int], self_recipe: str, src_name: str
) -> tuple[str, list[str]]:
    """Renumber flagship refs to 'Chapter N'; flag non-flagship refs."""
    warns: list[str] = []

    def repl(m: re.Match) -> str:
        ref = f"{int(m.group(1))}.{int(m.group(2))}"
        if ref in flagship_map:
            return f"Chapter {flagship_map[ref]}"
        # non-flagship reference that survived into print body -> needs rewording
        ctx = md[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
        warns.append(f"[PRINT-WARN] {src_name}: unresolved 'Recipe {ref}' "
                     f"(not in flagship) -> reword to concept. ...{ctx.strip()}...")
        return m.group(0)

    return RECIPE_REF_RE.sub(repl, md), warns


def collapse_rules(md: str) -> str:
    md = MULTI_RULE_RE.sub("---\n\n", md)
    return md.rstrip() + "\n"


def transform_recipe(
    md: str, entry: dict, flagship_map: dict[str, int], url: str,
    template: str | None, src_name: str
) -> tuple[str, list[str], dict[str, int]]:
    counts: dict[str, int] = {}
    # Per-recipe deep links into the digital edition.
    main_slug = src_name[:-3]
    ch, rr = entry["recipe"].split(".")
    arch_slug = f"chapter{int(ch):02d}.{int(rr):02d}-architecture"
    recipe_url = template.format(slug=main_slug) if template else url
    arch_url = template.format(slug=arch_slug) if template else url
    # 1. Pull the Related section out first (replaced by an inert placeholder),
    #    so the ref-rewriter never touches the list or its preserved comment.
    md, related_orig = split_related(md)
    md, counts["arch_callout"] = rewrite_arch_callout(md, arch_url)
    md, counts["tags"] = strip_tags(md)
    md, counts["nav_footer"] = strip_nav_footer(md)
    # 2. Rewrite inline refs on the body (placeholder is digit-free, so inert).
    md, warns = rewrite_recipe_refs(md, flagship_map, entry["recipe"], src_name)
    # 3. Reattach the digital-edition pointer (+ commented original) last.
    if related_orig is not None:
        md = md.replace(RELATED_PLACEHOLDER,
                        build_related_pointer(related_orig, recipe_url, url))
    counts["related"] = 1 if related_orig is not None else 0
    # 4. Any relative recipe link that survived becomes an absolute https target,
    #    so the PDF cannot carry file:// annotations exposing the build path.
    md, counts["abs_links"] = absolutise_links(md, url)
    md = collapse_rules(md)
    return md, warns, counts


# --------------------------------------------------------------------------- #
# Front / back matter
# --------------------------------------------------------------------------- #
def _qr_block(url: str) -> str:
    """Return an inline HTML block with the digital-edition QR (empty if asset missing)."""
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "digital-edition-qr.svg")
    try:
        with open(p, encoding="utf-8") as fh:
            svg = fh.read().strip()
    except OSError:
        return ""
    return (
        "\n\n<div class=\"qr-block\">\n"
        f"{svg}\n"
        f"<div class=\"qr-cap\">Scan to open the digital edition<br>{url}</div>\n"
        "</div>\n"
    )


def _frontmatter_file(name: str, **subs) -> str:
    """Read an editable front-matter page from print/frontmatter/.

    Returns "" when the file is absent, so deleting a page omits it rather than
    breaking the build. HTML comments are stripped: the files carry editing notes
    that must not reach the reader.
    """
    path = os.path.join(HERE, "frontmatter", name)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    for key, value in subs.items():
        text = text.replace("{" + key + "}", str(value))
    return text + "\n"


def front_matter(man: dict, built: list[dict]) -> list[tuple[str, str]]:
    """Return list of (css_class, markdown) front-matter sections."""
    y = man["copyright_year"]
    url = man["digital_edition_url"]
    title = man["title"]
    sub = man["subtitle"]
    author = man["author"]
    n = man["total_recipes_in_digital"]
    # All front-matter prose lives in print/frontmatter/*.md so it can be edited
    # without touching Python. Placeholders are substituted from the manifest, which
    # keeps the URL and counts from drifting; the digital edition URL has already
    # changed once. The Contents page below stays generated, since it is built from
    # the two-pass page map rather than authored.
    subs = dict(
        title=title, subtitle=sub, author=author, year=y,
        digital_url=url, recipe_count=n, extra_recipes=n - 15,
    )
    title_pg = _frontmatter_file("title-page.md", **subs)
    copyright_pg = _frontmatter_file("copyright-page.md", **subs)
    about_author = _frontmatter_file("about-the-author.md", **subs)
    preface = _frontmatter_file("preface.md", **subs)
    how_to = _frontmatter_file("how-to-use-this-book.md", **subs)
    before_phi = _frontmatter_file("before-you-send-phi.md", **subs)
    governance = _frontmatter_file("governance-and-responsible-ai.md", **subs)
    how_to = how_to + _qr_block(url)
    import os as _os, json as _json
    _pm = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "build", "toc-pagemap.json")
    try:
        _pmap = _json.load(open(_pm, encoding="utf-8"))
    except OSError:
        _pmap = {}
    items = []
    for b in built:
        cat = f"{b['print_chapter']} \u00b7 {b['chapter_name']}"
        pg = _pmap.get(str(b["print_chapter"]), "")
        items.append(
            f'<div class="toc-item"><div class="toc-cat">{cat}</div>'
            f'<div class="toc-line"><span class="toc-t">{b["title"]}</span>'
            f'<span class="toc-dots"></span><span class="toc-pg">{pg}</span></div></div>'
        )
    toc = '# Contents\n\n<div class="toc-wrap">\n' + "\n".join(items) + "\n</div>"
    return [
        ("frontmatter title-page", title_pg),
        ("frontmatter copyright-page", copyright_pg),
        ("frontmatter", about_author),
        ("frontmatter toc", toc),
        ("frontmatter", preface),
        ("frontmatter", how_to),
        ("frontmatter", before_phi),
        ("frontmatter", governance),
    ]


def appendix_index(man: dict):
    """Return an ('backmatter index', markdown) section for Appendix B, or None."""
    import os, json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index-terms.json")
    try:
        idx = json.load(open(p, encoding="utf-8"))
    except OSError:
        return None
    out = ["# Appendix B: Topic and Service Index", ""]
    out.append(
        "Cross-cutting topics, techniques, and AWS services, each pointing to the recipes "
        "(by number) where it appears. Pervasive elements common to most recipes, such as "
        "HIPAA and core AWS infrastructure, are omitted here; locate any recipe by number in "
        "Appendix A or in the digital edition."
    )
    out.append("")
    cur = None
    for term in idx:  # pre-sorted alphabetically
        c = term[0].upper()
        grp = "0-9" if c.isdigit() else c
        if grp != cur:
            cur = grp
            out.append(f"### {grp}")
            out.append("")
        out.append(f"**{term}** {', '.join(idx[term])}")
        out.append("")
    return ("backmatter index", "\n".join(out))


def appendix_catalog(man: dict):
    """Return an ('backmatter catalog', markdown) section for Appendix A, or None."""
    import os, json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "appendix-catalog.json")
    try:
        cat = json.load(open(p, encoding="utf-8"))
    except OSError:
        return None
    url = man["digital_edition_url"]
    n = man["total_recipes_in_digital"]
    out = ["# Appendix A: The Complete Recipe Catalog", ""]
    out.append(
        f"All {n} recipes in the digital cookbook, listed by chapter. The 15 marked "
        "*(in this volume)* are the flagship recipes you just read; every other recipe "
        f"is available in full in the digital edition at {url}."
    )
    out.append("")
    cur = None
    for e in cat:
        if e["chapter"] != cur:
            cur = e["chapter"]
            out.append(f"## Chapter {cur} \u00b7 {e['chapter_name']}")
            out.append("")
        marker = " *(in this volume)*" if e["in_volume"] else ""
        desc = (e.get("desc") or "").strip()
        line = f"**{e['recipe']} {e['title']}**{marker}."
        if desc:
            line += f" {desc}"
        out.append(line)
        out.append("")
    return ("backmatter catalog", "\n".join(out))


def back_matter(man: dict, built: list[dict]) -> list[tuple[str, str]]:
    url = man["digital_edition_url"]
    n = man["total_recipes_in_digital"]
    more = (
        "# There Are More Recipes Online\n\n"
        f"This volume is 15 of {n} recipes. The full digital cookbook covers "
        "every chapter in depth: additional recipes per capability, the "
        "complete AWS architectures, diagrams, and runnable examples, kept "
        "current as services and best practices evolve.\n\n"
        f"**Read the complete cookbook:** {url}\n"
    )
    return [("backmatter", more)]


# --------------------------------------------------------------------------- #
# Rendering (Markdown -> HTML -> PDF)
# --------------------------------------------------------------------------- #
def get_md_renderer(prefer: str = "markdown-it-py"):
    """Return a function md(str)->html(str) using the requested engine.

    The engine matters: different Markdown engines emit different HTML, which
    changes pagination, which changes the printed page count and therefore the
    cover spine width. Default to markdown-it-py because that is what the
    md-to-html site generator uses, so print and web stay consistent and the
    recorded page-count baseline remains comparable. Pass prefer="auto" for the
    old first-available behaviour.
    """
    def _python_markdown():
        import markdown  # python-markdown
        def render(md_text: str) -> str:
            return markdown.markdown(
                md_text,
                extensions=["extra", "sane_lists", "codehilite", "toc"],
            )
        return render, "python-markdown"

    def _markdown_it():
        from markdown_it import MarkdownIt
        mdit = MarkdownIt("commonmark", {"html": True}).enable("table")
        return (lambda t: mdit.render(t)), "markdown-it-py"

    def _mistune():
        import mistune
        r = mistune.create_markdown(plugins=["table", "strikethrough"])
        return (lambda t: r(t)), "mistune"

    builders = {
        "markdown-it-py": _markdown_it,
        "python-markdown": _python_markdown,
        "mistune": _mistune,
    }

    if prefer in builders:
        order = [prefer] + [k for k in builders if k != prefer]
    else:  # "auto"
        order = ["python-markdown", "markdown-it-py", "mistune"]

    for name in order:
        try:
            return builders[name]()
        except Exception:
            continue
    return None, None


PRINT_CSS_PATH = os.path.join(HERE, "print.css")

# allow importing sibling modules (tag_index) when run as a script
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def build_html(sections: list[tuple[str, str]], render, title: str) -> str:
    with open(PRINT_CSS_PATH, encoding="utf-8") as fh:
        css = fh.read()
    body = []
    for cls, md_text in sections:
        body.append(f'<section class="{cls}">\n{render(md_text)}\n</section>')
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title>"
        f"<style>{css}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


def set_pdf_metadata(pdf_path: str, man: dict) -> bool:
    """Replace Chrome's toolchain metadata with real document metadata.

    Chrome writes Creator as a full HeadlessChrome user-agent and Producer as Skia,
    both visible in any reader's document properties, and leaves Author, Subject and
    Keywords empty, which hurts catalogue discoverability. Rewrites the Info
    dictionary in place. Skipped with a warning if pypdf is unavailable.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        print("  [pdf] pypdf not installed; leaving Chrome metadata in place "
              "(pip install --user pypdf)", file=sys.stderr)
        return False
    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter(clone_from=reader)
        writer.add_metadata({
            "/Title": man.get("title", ""),
            "/Author": man.get("author", ""),
            "/Subject": man.get("subtitle", ""),
            "/Keywords": "healthcare, artificial intelligence, machine learning, "
                         "clinical informatics, architecture, HIPAA, AWS",
            "/Creator": man.get("title", ""),
            "/Producer": "HCLS AI/ML Cookbook print pipeline",
        })
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [pdf] metadata step failed ({exc})", file=sys.stderr)
        return False


def render_pdf(html_path: str, pdf_path: str) -> bool:
    """Render HTML -> PDF via puppeteer if available. Returns success."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("  [pdf] node not found; skipping PDF.", file=sys.stderr)
        return False
    out_dir = os.path.dirname(html_path)
    # reuse a node_modules/puppeteer if one exists anywhere obvious
    print_js = os.path.join(out_dir, "_print.js")
    with open(print_js, "w", encoding="utf-8") as fh:
        fh.write(
            "const p=require('puppeteer');(async()=>{const b=await p.launch("
            "{headless:'new',args:['--no-sandbox','--disable-setuid-sandbox']});"
            "const pg=await b.newPage();await pg.goto('file://'+process.argv[2],"
            "{waitUntil:'networkidle0',timeout:60000});"
            "await new Promise(r=>setTimeout(r,1500));"
            "await pg.pdf({path:process.argv[3],preferCSSPageSize:true,"
            "printBackground:true,outline:true,tagged:true});"
            "await b.close();"
            "console.log('PDF written');})().catch(e=>{"
            "console.error('PDF ERROR:',e.message);process.exit(1);});"
        )
    try:
        subprocess.run([node, print_js, html_path, pdf_path], check=True,
                       cwd=out_dir, timeout=180)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [pdf] render failed ({exc}). Install puppeteer in {out_dir}: "
              f"npm init -y && npm i puppeteer, then re-run with --pdf.",
              file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Build the flagship-15 print edition.")
    ap.add_argument("--all", action="store_true",
                    help="include all 15 recipes (default: approved only)")
    ap.add_argument("--pdf", action="store_true", help="also render 6x9 PDF")
    ap.add_argument("--epub", action="store_true", help="also build an accessible EPUB 3")
    ap.add_argument("--engine", default="markdown-it-py",
                    choices=["markdown-it-py", "python-markdown", "mistune", "auto"],
                    help="Markdown engine (default: markdown-it-py, matching the "
                         "site build; engine choice changes pagination)")
    ap.add_argument("--out", default=os.path.join(HERE, "build"),
                    help="output directory (default: print/build)")
    args = ap.parse_args()

    man = load_manifest()
    url = man["digital_edition_url"]
    template = man.get("recipe_url_template")
    flagship_map = {e["recipe"]: e["print_chapter"] for e in man["flagship"]}

    out = args.out
    os.makedirs(out, exist_ok=True)

    selected = [e for e in man["flagship"] if args.all or e["approved"]]
    built: list[dict] = []
    all_warns: list[str] = []
    skipped: list[str] = []

    for e in selected:
        src = resolve_source(e["recipe"])
        if not src:
            skipped.append(f"{e['recipe']} ({e['title']}) - source file not found")
            continue
        src_name = os.path.basename(src)
        md = open(src, encoding="utf-8").read()
        adapted, warns, counts = transform_recipe(md, e, flagship_map, url, template, src_name)
        # prepend a print chapter heading so the running structure is by chapter
        slug = src_name[:-3]
        outfile = os.path.join(out, f"{e['print_chapter']:02d}-{slug}.md")
        with open(outfile, "w", encoding="utf-8") as fh:
            fh.write(adapted)
        all_warns.extend(warns)
        rec = dict(e)
        rec.update(src=src_name, outfile=os.path.basename(outfile),
                   md=adapted, counts=counts, warns=len(warns))
        built.append(rec)
        c = counts
        print(f"  ch{e['print_chapter']:02d} {e['recipe']:>4} {e['title'][:34]:34} "
              f"nav-{c['nav_footer']} rel-{c['related']} arch-{c['arch_callout']} "
              f"tags-{c['tags']} warn-{len(warns)}")

    # assemble book.md + book.html (re-callable so the TOC two-pass can rebuild)
    render, engine = get_md_renderer(args.engine)

    def _assemble(include_pgm: bool = True) -> bool:
        """Assemble book.md and book.html.

        include_pgm controls the page-extraction anchors. They are needed on the
        first render so extract-toc-pages.js can find each chapter's page, but they
        must not ship: at 1px they are invisible on paper yet remain in the text
        layer, surfacing in copy-paste, search, screen readers and any EPUB
        conversion. The anchor is absolutely positioned in print.css, so dropping it
        cannot shift pagination.
        """
        sections: list[tuple[str, str]] = []
        sections += front_matter(man, built)
        for b in built:
            _md = re.sub(r"[\u2b50\U0001F536\U0001F537\U0001F3E5\uFE0F]", "", b["md"])
            _anchor = (f'<span class="pgm">PGMK{b["print_chapter"]}ENDPGMK</span>\n\n'
                       if include_pgm else "")
            sections.append(("recipe", _anchor + _md))
        sections += back_matter(man, built)
        _ap = appendix_catalog(man)
        if _ap:
            sections.append(_ap)
        _ix = None
        try:
            import tag_index as _ti
            _ix = _ti.build(built, man.get("digital_edition_url", ""))
        except Exception as exc:                        # fall back to the curated index
            print(f"  [appendix-b] tag index unavailable ({exc}); "
                  f"using curated index-terms.json", file=sys.stderr)
            _ix = appendix_index(man)
        if _ix:
            sections.append(_ix)
        book_md = "\n\n<!-- ===== PAGE ===== -->\n\n".join(s[1] for s in sections)
        with open(os.path.join(out, "book.md"), "w", encoding="utf-8") as fh:
            fh.write(book_md)
        if not render:
            return False
        html = build_html(sections, render, man["title"])
        with open(os.path.join(out, "book.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        return True

    html_ok = _assemble()
    if args.epub:
        epub_sections = build_sections(man, built, include_pgm=False)
        epub_path = os.path.join(out, "book.epub")
        if render_epub(epub_sections, man, epub_path):
            print(f"    book.epub: {len(epub_sections)} sections, {os.path.getsize(epub_path)//1024} KB")

    # warnings report
    warn_path = os.path.join(out, "print-warnings.txt")
    with open(warn_path, "w", encoding="utf-8") as fh:
        fh.write(f"Print build warnings - {_dt.datetime.now().isoformat()}\n")
        fh.write(f"Built {len(built)} recipe(s); {len(all_warns)} ref warning(s).\n\n")
        for w in all_warns:
            fh.write(w + "\n")
        if skipped:
            fh.write("\nSkipped:\n")
            for s in skipped:
                fh.write("  " + s + "\n")

    # summary
    print(f"\nbuilt {len(built)} recipe(s) -> {out}")
    print(f"  book.md: {os.path.getsize(os.path.join(out, 'book.md')):,} bytes")
    if html_ok:
        print(f"  book.html: rendered via {engine}")
    else:
        print("  book.html: SKIPPED (no markdown engine; run with the "
              "md-to-html venv python, or pip install markdown)")
    print(f"  ref warnings: {len(all_warns)} (see print-warnings.txt)")
    if skipped:
        print(f"  skipped: {len(skipped)} (not yet present / unresolved)")

    if args.pdf:
        if not html_ok:
            print("  [pdf] cannot render PDF without book.html", file=sys.stderr)
        else:
            pdf = os.path.join(out, "book.pdf")
            if render_pdf(os.path.join(out, "book.html"), pdf):
                # Two-pass TOC: extract each recipe's page from pass 1, then
                # rebuild with page numbers and re-render. Degrades gracefully.
                node = shutil.which("node")
                extractor = os.path.join(HERE, "extract-toc-pages.js")
                if node and os.path.exists(extractor) and out == os.path.join(HERE, "build"):
                    try:
                        subprocess.run([node, extractor], check=True, timeout=120,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        _assemble(include_pgm=False)
                        render_pdf(os.path.join(out, "book.html"), pdf)
                        print("  book.pdf: TOC page numbers applied (two-pass); "
                              "page anchors stripped")
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [toc] page-number pass skipped ({exc})", file=sys.stderr)
                if set_pdf_metadata(pdf, man):
                    print("  book.pdf: document metadata set")
                sz = os.path.getsize(pdf)
                print(f"  book.pdf: {sz/1024:.0f} KB")

    return 0


# --------------------------------------------------------------------------- #
# EPUB (accessible EPUB 3)
# --------------------------------------------------------------------------- #
EPUB_CSS = """\
html, body { margin: 0; padding: 0; }
body { font-family: serif; line-height: 1.5; }
h1, h2, h3, h4, h5 { font-family: sans-serif; line-height: 1.2; }
h1 { page-break-before: always; break-before: page; }
p { orphans: 2; widows: 2; }
code, pre { font-family: monospace; }
pre { white-space: pre-wrap; overflow-wrap: break-word; background: #f4f4f4;
      padding: 0.6em; border-radius: 4px; }
code { background: #f4f4f4; padding: 0 0.2em; }
pre code { background: transparent; padding: 0; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #999; padding: 0.3em 0.5em; text-align: left;
         vertical-align: top; }
blockquote { border-left: 3px solid #999; margin: 1em 0; padding: 0.2em 1em; }
img { max-width: 100%; height: auto; }
"""


def _section_title(md_text: str) -> str | None:
    """Derive a navigation title from a section's first H1."""
    m = re.search(r"(?m)^#\s+(.+?)\s*$", md_text)
    if not m:
        return None
    t = m.group(1)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)   # strip markdown links
    t = re.sub(r"[*`_]", "", t)                       # strip emphasis marks
    return t.strip() or None


def build_sections(man: dict, built: list, include_pgm: bool = True) -> list:
    """Assemble the ordered (css_class, markdown) sections for the book.

    Mirrors main()._assemble so the EPUB and the PDF/HTML share the exact same
    adapted content. EPUB callers pass include_pgm=False: the page anchors are
    print-only and must not ship in the EPUB text layer.
    """
    sections: list = []
    sections += front_matter(man, built)
    for b in built:
        _md = re.sub(r"[\u2b50\U0001F536\U0001F537\U0001F3E5\uFE0F]", "", b["md"])
        _anchor = (f'<span class="pgm">PGMK{b["print_chapter"]}ENDPGMK</span>\n\n'
                   if include_pgm else "")
        sections.append(("recipe", _anchor + _md))
    sections += back_matter(man, built)
    _ap = appendix_catalog(man)
    if _ap:
        sections.append(_ap)
    try:
        import tag_index as _ti
        _ix = _ti.build(built, man.get("digital_edition_url", ""))
    except Exception as exc:
        print(f"  [appendix-b] tag index unavailable ({exc}); "
              f"using curated index-terms.json", file=sys.stderr)
        _ix = appendix_index(man)
    if _ix:
        sections.append(_ix)
    return sections


def _epub_add_package_lang(epub_path: str, lang: str = "en-US") -> None:
    """Add xml:lang to the OPF <package> element (EbookLib omits it).

    Rewrites the EPUB zip in place, keeping mimetype first and stored so the
    OCF container stays valid.
    """
    import zipfile
    zin = zipfile.ZipFile(epub_path, "r")
    names = zin.namelist()
    data = {n: zin.read(n) for n in names}
    zin.close()
    opf = next((n for n in names if n.endswith("content.opf")), None)
    if opf:
        text = data[opf].decode("utf-8")
        head = text.split(">", 1)[0]
        if "xml:lang=" not in head:
            text = re.sub(r"(<package\b)", r'\1 xml:lang="%s"' % lang, text, count=1)
            data[opf] = text.encode("utf-8")
    tmp = epub_path + ".tmp"
    zout = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)
    if "mimetype" in data:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zout.writestr(info, data["mimetype"])
    for n in names:
        if n == "mimetype":
            continue
        zout.writestr(n, data[n])
    zout.close()
    os.replace(tmp, epub_path)


def render_epub(sections: list, man: dict, epub_path: str) -> bool:
    """Build an accessible EPUB 3 from the assembled sections."""
    import uuid
    try:
        from ebooklib import epub
        from markdown_it import MarkdownIt
    except Exception as exc:
        print(f"  [epub] EbookLib/markdown-it not available ({exc}); "
              f"pip install --user EbookLib markdown-it-py", file=sys.stderr)
        return False

    mdit = MarkdownIt("commonmark", {"html": True, "xhtmlOut": True}).enable("table")

    book = epub.EpubBook()
    book.set_identifier("urn:uuid:" + str(uuid.uuid4()))
    book.set_title(man["title"])
    book.set_language("en-US")
    if man.get("author"):
        book.add_author(man["author"])
    if man.get("subtitle"):
        book.add_metadata("DC", "description", man["subtitle"])
    if man.get("copyright_year"):
        book.add_metadata("DC", "rights",
                          f"Copyright {man['copyright_year']} {man.get('author', '')}".strip())

    # EPUB Accessibility 1.1 / schema.org metadata (the A-3 gate).
    a11y = [
        ("schema:accessMode", "textual"),
        ("schema:accessModeSufficient", "textual"),
        ("schema:accessibilityFeature", "tableOfContents"),
        ("schema:accessibilityFeature", "structuralNavigation"),
        ("schema:accessibilityFeature", "readingOrder"),
        ("schema:accessibilityFeature", "displayTransformability"),
        ("schema:accessibilityHazard", "none"),
        ("schema:accessibilitySummary",
         "This reflowable publication is fully textual with a complete table of "
         "contents and semantic structural navigation. It contains no images "
         "essential to understanding and declares no known accessibility hazards."),
    ]
    for prop, val in a11y:
        book.add_metadata(None, "meta", val, {"property": prop})

    css = epub.EpubItem(uid="style", file_name="style/epub.css",
                        media_type="text/css", content=EPUB_CSS)
    book.add_item(css)

    recipe_idx = [i for i, (cls, _) in enumerate(sections) if cls == "recipe"]
    first_r = recipe_idx[0] if recipe_idx else -1
    last_r = recipe_idx[-1] if recipe_idx else -1

    chapters = []
    for i, (cls, md_text) in enumerate(sections):
        if first_r != -1 and i < first_r:
            etype = "frontmatter"
        elif first_r != -1 and i > last_r:
            etype = "backmatter"
        else:
            etype = "bodymatter"
        # Strip HTML comments: build-time PRINT-TODO notes embed markdown that
        # contains "--", which is illegal inside an XML/XHTML comment, and readers
        # never see comments anyway.
        md_text = re.sub(r"<!--.*?-->", "", md_text, flags=re.S)
        title = _section_title(md_text) or f"Section {i + 1}"
        body = mdit.render(md_text)
        # Normalize lenient HTML to well-formed XHTML (raw-HTML passthrough,
        # stray "<" in prose, void elements) so every chapter parses as XML.
        try:
            import lxml.html as _lh
            from lxml import etree as _et
            _frag = _lh.fragment_fromstring(body, create_parent="div")
            body = _et.tostring(_frag, encoding="unicode", method="xml")
        except Exception as _exc:
            print(f"  [epub] XHTML normalize skipped for a section ({_exc})", file=sys.stderr)
        item = epub.EpubHtml(title=title, file_name=f"text/ch{i + 1:03d}.xhtml", lang="en-US")
        item.add_item(css)
        item.content = (
            "<html xmlns=\"http://www.w3.org/1999/xhtml\" "
            "xmlns:epub=\"http://www.idpf.org/2007/ops\" xml:lang=\"en-US\" lang=\"en-US\">"
            f"<head><title>{_html.escape(title)}</title>"
            "<link rel=\"stylesheet\" type=\"text/css\" href=\"../style/epub.css\"/></head>"
            f"<body epub:type=\"{etype}\">\n{body}\n</body></html>"
        )
        book.add_item(item)
        chapters.append(item)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(epub_path, book)
    _epub_add_package_lang(epub_path, "en-US")
    return True



if __name__ == "__main__":
    raise SystemExit(main())
