// Two-pass TOC support: read the rendered PDF, find each recipe's invisible
// page anchor (PGMK<chapter>ENDPGMK), and write build/toc-pagemap.json mapping
// print-chapter -> printed page number. build.py reads that map on the next
// render to emit TOC page numbers. Uses the pdfjs-dist installed alongside
// puppeteer in build/node_modules (gitignored).
const path = require("path");
const fs = require("fs");
const dir = __dirname;
const pdfjs = require(path.join(dir, "build", "node_modules", "pdfjs-dist", "legacy", "build", "pdf.js"));
const PDF = path.join(dir, "build", "book.pdf");
const OUT = path.join(dir, "build", "toc-pagemap.json");

(async () => {
  const data = new Uint8Array(fs.readFileSync(PDF));
  const doc = await pdfjs.getDocument({ data, useSystemFonts: true }).promise;
  const map = {};
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const tc = await page.getTextContent();
    const text = tc.items.map((it) => it.str).join("");
    const re = /PGMK(\d+)ENDPGMK/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (!(m[1] in map)) map[m[1]] = i;
    }
  }
  fs.writeFileSync(OUT, JSON.stringify(map, null, 2));
  console.log("toc-pagemap:", JSON.stringify(map));
})().catch((e) => { console.error(e); process.exit(1); });
