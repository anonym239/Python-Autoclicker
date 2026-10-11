"""Erzeugt web/icon.svg + PNG-Icons (Grasblock, Pixel-Art) ohne Zusatzmodule.

    python tools/make_icons.py
"""

import os
import struct
import zlib

# 16x16 Grasblock. Buchstaben -> Farben.
PALETTE = {
    "G": (0x73, 0xC1, 0x4A), "g": (0x5F, 0xA8, 0x3A), "d": (0x4B, 0x8C, 0x2C),
    "B": (0x7A, 0x52, 0x33), "b": (0x5D, 0x3C, 0x24), "c": (0x8D, 0x60, 0x40),
    "s": (0x9A, 0x9A, 0x9A),
}
PIXELS = [
    "GGGgggGGgGGggGGG",
    "gggggGGgGGGgggGg",
    "ggGGgggGdggggGgg",
    "gdgggggggggGGgGg",
    "ggggdgggggggggGg",
    "ddgdggddgdggdgdd",
    "BcBdBBbBBBBBdBBB",
    "BccBbBBbBccBBcBB",
    "BBBBcBBbBBBBBbBc",
    "bBBsBccBBBBBcBBc",
    "BBBBBcBBcBBbBBBB",
    "BbBBBBBBBbBBBcBB",
    "BcBcBBBBBBBBcsBB",
    "BbBBBBBcBbBBBBbB",
    "BbBBBbBBBBBcBBbB",
    "BBcBBBBBBbBBBBBB",
]

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def svg() -> str:
    rects = []
    for y, row in enumerate(PIXELS):
        for x, ch in enumerate(row):
            r, g, b = PALETTE[ch]
            rects.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#{r:02x}{g:02x}{b:02x}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">'
            + "".join(rects) + "</svg>\n")


def png(size: int, pad: int = 0, bg=(0x14, 0x16, 0x1B)) -> bytes:
    inner = size - 2 * pad
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            x, y = px - pad, py - pad
            if 0 <= x < inner and 0 <= y < inner:
                row += bytes(PALETTE[PIXELS[y * 16 // inner][x * 16 // inner]])
            else:
                row += bytes(bg)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    with open(os.path.join(ROOT, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(svg())
    for name, size, pad in (("icon-192.png", 192, 24), ("icon-512.png", 512, 64),
                            ("apple-touch-icon.png", 180, 22)):
        with open(os.path.join(ROOT, name), "wb") as f:
            f.write(png(size, pad))
    print("Icons geschrieben nach", ROOT)


if __name__ == "__main__":
    main()
