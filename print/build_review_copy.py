#!/usr/bin/env python3
"""Build an advance review copy (galley) PDF for editors and reporters.

Contents: the front cover, then the finished print interior (print/build/book.pdf)
with "Advance review copy. Not for resale." stamped in the top margin of every
page. Run print/build.py --pdf first so the interior is current.

Not for upload to KDP: the stamp is for press copies only. Output:
print/build/review-copy.pdf (git-ignored with the rest of print/build/).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build  # noqa: E402

COVER = os.path.join(build.BOOK_ROOT, "BookCoverV1.png")
STAMP_TEXT = "Advance review copy. Not for resale."

# Both pages are 6x9 to match the interior. Font paths are relative to
# print/build/, where the HTML is written, as in print.css.
_PAGE_CSS = """
@page { size: 6in 9in; margin: 0; }
html, body { margin: 0; padding: 0; }
"""
COVER_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>{_PAGE_CSS}
img {{ display: block; width: 6in; height: 9in; object-fit: cover; }}
</style></head><body><img src="file://{COVER}" alt="Front cover"></body></html>"""
STAMP_HTML = f"""<!doctype html><html><head><meta charset="utf-8"><style>{_PAGE_CSS}
@font-face {{ font-family: "Gelasio"; font-style: italic;
  src: url("../assets/fonts/Gelasio-Italic.ttf") format("truetype"); }}
.stamp {{ position: fixed; top: 0.38in; left: 0; right: 0; text-align: center;
  font-family: "Gelasio", serif; font-style: italic; font-size: 7.5pt;
  letter-spacing: 0.4px; color: #777; }}
</style></head><body><div class="stamp">{STAMP_TEXT}</div></body></html>"""


def _render(out: str, name: str, html: str) -> str:
    html_path = os.path.join(out, f"{name}.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    pdf_path = os.path.join(out, f"{name}.pdf")
    if not build.render_pdf(html_path, pdf_path):
        raise SystemExit(f"could not render {name}.pdf")
    return pdf_path


def main() -> int:
    from pypdf import PdfReader, PdfWriter

    out = os.path.join(HERE, "build")
    interior = os.path.join(out, "book.pdf")
    if not os.path.exists(interior):
        print("print/build/book.pdf not found; run print/build.py --pdf first")
        return 1
    if not os.path.exists(COVER):
        print("cover not found:", COVER)
        return 1

    cover = PdfReader(_render(out, "_review-cover", COVER_HTML)).pages[0]
    stamp = PdfReader(_render(out, "_review-stamp", STAMP_HTML)).pages[0]

    writer = PdfWriter()
    writer.append(interior)                 # keeps the bookmarks and TOC links
    for page in writer.pages:
        page.merge_page(stamp)
        page.compress_content_streams()     # merge_page leaves them uncompressed
    writer.insert_page(cover, 0)
    writer.compress_identical_objects()     # one copy of the stamp font, not 299

    man = build.load_manifest()
    writer.add_metadata({
        "/Title": f"{man['title']} (Advance Review Copy)",
        "/Author": man["author"],
        "/Subject": man["subtitle"],
    })
    pdf_path = os.path.join(out, "review-copy.pdf")
    with open(pdf_path, "wb") as fh:
        writer.write(fh)
    print(f"  review-copy.pdf: {len(writer.pages)} pages, "
          f"{os.path.getsize(pdf_path) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
