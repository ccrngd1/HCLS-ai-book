#!/usr/bin/env python3
"""One-off: build a single-chapter sampler PDF.

Contents: all the prose front matter MINUS the author name (blanked on the title
and copyright pages) and MINUS the About-the-Author bio, followed by one flagship
recipe with its digital-edition links removed. No Table of Contents, no back
matter, no appendices.

Reuses print/build.py wholesale so the sampler's typography, fonts and page size
match the book exactly. Output: print/build/sampler.{html,pdf}.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build  # noqa: E402

SAMPLER_RECIPE = "10.7"  # editor's pick: Ambient Clinical Documentation


def adapt_chapter(md, entry, flagship_map, url, template, src_name):
    """Same cleanups as build.transform_recipe, but DROP the digital-edition
    pointers (architecture-companion callout and Related-Recipes pointer) rather
    than rewriting them, and strip internal/digital links while keeping external
    citations (e.g. journal and vendor references in As Seen In Production)."""
    domain = re.sub(r"^https?://", "", (url or "")).split("/")[0]
    md, _related = build.split_related(md)                 # Related -> heading + placeholder
    md = build.ARCH_CALLOUT_RE.sub("", md)                 # drop the arch-companion callout
    md, _ = build.strip_tags(md)
    md, _ = build.strip_nav_footer(md)
    md, warns = build.rewrite_recipe_refs(md, flagship_map, entry["recipe"], src_name)
    # remove the whole Related Recipes section (heading + placeholder)
    md = re.sub(r"(?ms)^##\s+Related Recipes\s*\n+" + re.escape(build.RELATED_PLACEHOLDER) + r"\s*",
                "", md)
    md = md.replace(build.RELATED_PLACEHOLDER, "")
    # drop schemeless (relative) markdown links, keep the link text
    md = re.sub(r"\[([^\]]+)\]\((?!https?:|mailto:|#)[^)]*\)", r"\1", md)
    # drop any absolute link or autolink to the digital-edition domain, keep text
    if domain:
        md = re.sub(r"\[([^\]]+)\]\(https?://[^)]*" + re.escape(domain) + r"[^)]*\)", r"\1", md)
        md = re.sub(r"<https?://[^>]*" + re.escape(domain) + r"[^>]*>", "", md)
    md = build.collapse_rules(md)
    return md, warns


def scrub_pii(txt, url, domain):
    """Remove the digital-edition QR (its code encodes the author's personal
    domain) and every occurrence of that personal URL/domain, leaving prose
    readable. The generic phrase 'digital edition' is not identifying and stays."""
    # 1. the QR block: the SVG encodes the personal URL even though no literal text
    txt = re.sub(r'(?s)<div class="qr-block">.*?</div>\s*</div>', "", txt)
    # 2. the copyright "Digital edition (all N recipes): URL" line
    txt = re.sub(r'(?m)^\s*Digital edition \(all [^\n]*\n?', "", txt)
    # 3. parenthetical " (URL)" -> removed
    txt = re.sub(r'\s*\(\s*' + re.escape(url) + r'\s*\)', "", txt)
    # 4. " at URL" -> removed
    txt = re.sub(r'\s+at\s+' + re.escape(url), "", txt)
    # 5. any remaining link/autolink/bare URL to the personal domain
    if domain:
        txt = re.sub(r'<?\(?\s*https?://[^\s>)\]]*' + re.escape(domain) + r'[^\s>)\]]*\s*\)?>?',
                     "", txt)
    txt = re.sub(r'[ \t]{2,}', ' ', txt)                # tidy any double spaces left behind
    return txt


def main():
    man = build.load_manifest()
    url = man["digital_edition_url"]
    template = man.get("recipe_url_template")
    flagship_map = {e["recipe"]: e["print_chapter"] for e in man["flagship"]}
    entry = next((e for e in man["flagship"] if e["recipe"] == SAMPLER_RECIPE), None)
    if not entry:
        print("recipe not in manifest:", SAMPLER_RECIPE)
        return 1
    src = build.resolve_source(SAMPLER_RECIPE)
    if not src:
        print("source not found for", SAMPLER_RECIPE)
        return 1
    src_name = os.path.basename(src)
    md = open(src, encoding="utf-8").read()
    chapter_md, warns = adapt_chapter(md, entry, flagship_map, url, template, src_name)
    chapter_md = re.sub(r"[\u2b50\U0001F536\U0001F537\U0001F3E5\uFE0F]", "", chapter_md)

    built = [dict(entry, src=src_name, md=chapter_md)]

    # Front matter with the author name blanked out.
    man_anon = dict(man)
    man_anon["author"] = ""
    fm = build.front_matter(man_anon, built)

    # Recreate the About-the-Author text so we can identify and drop that section.
    about_txt = build._frontmatter_file(
        "about-the-author.md",
        title=man["title"], subtitle=man["subtitle"], author="",
        year=man["copyright_year"], digital_url=url,
        recipe_count=man["total_recipes_in_digital"],
        extra_recipes=man["total_recipes_in_digital"] - 15,
    ).strip()

    sections = []
    for cls, txt in fm:
        if "toc" in cls:                                   # no TOC in a 1-chapter sampler
            continue
        t = txt.strip()
        if t and (t == about_txt or "About the Author" in t):   # drop the bio
            continue
        if "title-page" in cls:                            # remove the now-empty author line
            txt = re.sub(r"(?m)^\*\*\*\*\s*$", "", txt)
            txt = re.sub(r"(?ms)\n+&nbsp;\s*\Z", "\n", txt)
            txt = txt.rstrip() + "\n"
        if "copyright-page" in cls:                        # "Copyright (c) 2026 ." -> "... 2026."
            txt = re.sub(r"(\u00a9\s*\d{4})\s+\.", r"\1.", txt)
        sections.append((cls, txt))

    sections.append(("recipe", chapter_md))

    # Final pass: strip the QR and every occurrence of the personal domain/URL.
    domain = re.sub(r"^https?://", "", (url or "")).split("/")[0]
    sections = [(cls, scrub_pii(txt, url, domain)) for cls, txt in sections]

    render, engine = build.get_md_renderer("markdown-it-py")
    html = build.build_html(sections, render, man["title"])
    out = os.path.join(HERE, "build")
    os.makedirs(out, exist_ok=True)
    html_path = os.path.join(out, "sampler.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    pdf_path = os.path.join(out, "sampler.pdf")
    if build.render_pdf(html_path, pdf_path):
        build.set_pdf_metadata(pdf_path, man_anon)
        print(f"  sampler.pdf: {os.path.getsize(pdf_path) // 1024} KB")
    print(f"  chapter: {SAMPLER_RECIPE} {entry['title']}  (ref-warns: {len(warns)})")
    print(f"  sections: {[c for c, _ in sections]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
