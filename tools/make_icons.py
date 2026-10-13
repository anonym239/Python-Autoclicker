"""Erzeugt das App-Icon in allen Groessen.

    python tools/make_icons.py

Schreibt web/icon.svg + web/icon-256.png (Fenster-Icon) und assets/icon.ico (fuer .exe und Installer). Zum Rendern wird Node.js mit
Playwright gebraucht (nur fuer Entwickler, nicht zum Benutzen der App).
"""

import json
import os
import struct
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#2f8cff"/><stop offset="1" stop-color="#0052cc"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#bg)"/>
<g stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".9">
<path d="M24 8v5"/><path d="M8 22h5"/><path d="M12.7 10.7l3.5 3.5"/></g>
<path d="M24 22v28l7-6.5 5 10.5 5-2.2-5-10.3h9z" fill="#fff" stroke="#003b99" stroke-width="2.4" stroke-linejoin="round"/>
</svg>
"""

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

RENDER_JS = r"""
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const [svgFile, outDir, sizesJson] = process.argv.slice(2);
(async () => {
  const svg = fs.readFileSync(svgFile, 'utf8');
  const b = await chromium.launch();
  for (const s of JSON.parse(sizesJson)) {
    const p = await b.newPage({ viewport: { width: s, height: s } });
    await p.setContent(`<style>html,body{margin:0;background:transparent}</style>` +
      `<img src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}" width="${s}" height="${s}">`);
    await p.screenshot({ path: `${outDir}/${s}.png`, omitBackground: true });
    await p.close();
  }
  await b.close();
})();
"""


def write_ico(path: str, pngs: dict) -> None:
    sizes = sorted(pngs)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s in sizes:
        data = pngs[s]
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def main():
    with open(os.path.join(ROOT, "web", "icon.svg"), "w", encoding="utf-8") as f:
        f.write(ICON_SVG)
    sizes = sorted(ICO_SIZES)
    with tempfile.TemporaryDirectory() as tmp:
        svg_file = os.path.join(tmp, "icon.svg")
        js_file = os.path.join(tmp, "render.js")
        with open(svg_file, "w", encoding="utf-8") as f:
            f.write(ICON_SVG)
        with open(js_file, "w", encoding="utf-8") as f:
            f.write(RENDER_JS)
        subprocess.run(["node", js_file, svg_file, tmp, json.dumps(sizes)], check=True)
        pngs = {}
        for s in sizes:
            with open(os.path.join(tmp, f"{s}.png"), "rb") as f:
                pngs[s] = f.read()
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    write_ico(os.path.join(ROOT, "assets", "icon.ico"), {s: pngs[s] for s in ICO_SIZES})
    with open(os.path.join(ROOT, "web", "icon-256.png"), "wb") as f:  # grosses Fenster-Icon
        f.write(pngs[256])
    print("Icons geschrieben.")


if __name__ == "__main__":
    main()
