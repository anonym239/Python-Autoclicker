"""Werkzeug-Erkennung fuer Minecraft PvP / CPS-Boost (plattformunabhaengig).

Idee: Mit Werkzeug (Spitzhacke, Axt, Schere ...) in der Hand soll die Maustaste
normal gehalten werden – sonst kann man z. B. bei BedWars das Bett nicht abbauen.
Minecraft verraet anderen Programmen nicht, was man in der Hand haelt (und das
Spiel auszulesen waere ein Hack). Deshalb wird die Hotbar auf dem Bildschirm
angeschaut:

- analyze() findet die Hotbar und den gewaehlten Platz (heller Auswahlrahmen),
  fuer jede GUI-Groesse.
- item_sample() schneidet das Item aus dem Platz aus (16x16) und trennt es vom
  Hintergrund -> Umriss (Maske) + Bild mit transparentem Hintergrund.
- Beim Anlernen wird der Umriss gespeichert. Spaeter zaehlt jedes Item mit
  gleichem Umriss als Werkzeug – egal auf welchem Platz, egal welches Material
  (Holz-, Eisen-, Diamant-Spitzhacke haben denselben Umriss).
"""

from __future__ import annotations

import base64
import struct
import zlib

SLOTS = 9
HOTBAR_W, HOTBAR_H = 182, 22  # Minecraft-GUI-Einheiten
CAPTURE_GUI_H = 24            # so viel vom unteren Rand wird gebraucht (Auswahlrahmen ragt 1 heraus)
MAX_SCALE = 8
ITEM = 16                     # Items sind 16x16 GUI-Pixel
MATCH_ROWS = 12               # untere Zeilen nicht vergleichen (Haltbarkeitsbalken, Anzahl)
MIN_ITEM_PIXELS = 10          # weniger = leerer Platz
MATCH_IOU = 0.72              # so aehnlich muss der Umriss sein


def auto_gui_scale(width: int, height: int) -> int:
    """GUI-Groesse "Automatisch" wie in Minecraft."""
    scale = 1
    while scale < MAX_SCALE and width // (scale + 1) >= 320 and height // (scale + 1) >= 240:
        scale += 1
    return scale


class Shot:
    """Bildschirmausschnitt: unterer Rand des Spielfensters (BGRA, Zeilen von oben)."""

    def __init__(self, width: int, height: int, pixels: bytes, client_h: int):
        self.w, self.h = width, height
        self.pixels = pixels
        self.top = client_h - height  # y des Ausschnitts im Fenster
        self.client_h = client_h

    def rgb(self, x: int, y: int):
        """Pixel in Fensterkoordinaten -> (r, g, b) oder None ausserhalb."""
        yy = y - self.top
        if not (0 <= x < self.w and 0 <= yy < self.h):
            return None
        i = (yy * self.w + x) * 4
        b, g, r = self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]
        return r, g, b


def _luma(px) -> float:
    r, g, b = px
    return 0.299 * r + 0.587 * g + 0.114 * b


def _dist(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _layout(width: int, height: int, scale: int):
    """-> (x0, y0) der Hotbar in Pixeln (wie Minecraft sie zeichnet)."""
    gw, gh = -(-width // scale), -(-height // scale)  # aufgerundet
    return (gw // 2 - HOTBAR_W // 2) * scale, (gh - HOTBAR_H) * scale


def _ring_brightness(shot: Shot, x0: int, y0: int, slot: int, s: int) -> float:
    """Mittlere Helligkeit des Auswahlrahmens um einen Platz.

    Der Rahmen ist 24 GUI breit und beginnt 1 ueber der Hotbar. Benutzt werden
    oberer Rand und beide Seiten (der untere ist je nach Version abgeschnitten);
    pro Stelle zaehlt das hellere der beiden aeusseren Rahmen-Pixel."""
    left = x0 + (slot * 20 - 1) * s
    top = y0 - 1 * s
    total, n = 0.0, 0
    h = s // 2
    for i in range(2, 21, 2):  # Ecken auslassen
        spots = (((left + i * s, top), (left + i * s, top + s)),                    # oben
                 ((left, top + i * s), (left + s, top + i * s)),                    # links
                 ((left + 23 * s, top + i * s), (left + 22 * s, top + i * s)))      # rechts
        for outer, inner in spots:
            a = shot.rgb(outer[0] + h, outer[1] + h)
            b = shot.rgb(inner[0] + h, inner[1] + h)
            if a is None or b is None:
                return 0.0
            total += max(_luma(a), _luma(b))
            n += 1
    return total / n if n else 0.0


def analyze(shot: Shot, width: int):
    """Hotbar suchen. -> dict(scale, slot 1–9, confidence, x0, y0) oder None.

    Probiert alle GUI-Groessen; gewaehlt ist der Platz mit dem hellsten Rahmen,
    wenn er sich deutlich von den anderen abhebt."""
    best = None
    for s in range(1, MAX_SCALE + 1):
        if HOTBAR_W * s > width or CAPTURE_GUI_H * s > shot.h:
            break
        x0, y0 = _layout(width, shot.client_h, s)
        rings = [_ring_brightness(shot, x0, y0, i, s) for i in range(SLOTS)]
        order = sorted(range(SLOTS), key=lambda i: rings[i], reverse=True)
        top, second = rings[order[0]], rings[order[1]]
        conf = top - second
        if top >= 130 and conf >= 35 and (best is None or conf > best["confidence"]):
            best = {"scale": s, "slot": order[0] + 1, "confidence": round(conf, 1), "x0": x0, "y0": y0}
    return best


class Item:
    """Item aus einem Hotbar-Platz: Pixel, Umriss (Maske) und Hintergrundfarbe."""

    def __init__(self, rows, mask, bg):
        self.rows = rows      # 16x16 (r, g, b)
        self.mask = mask      # 256 bool, zeilenweise
        self.bg = bg

    @property
    def size(self) -> int:
        return sum(self.mask)

    @property
    def empty(self) -> bool:
        return self.size < MIN_ITEM_PIXELS

    def mask_hex(self) -> str:
        bits = 0
        for i, on in enumerate(self.mask):
            if on:
                bits |= 1 << i
        return f"{bits:064x}"

    def icon(self) -> str:
        """Bild mit durchsichtigem Hintergrund als data:-URL."""
        rgba = [[(*px, 255 if self.mask[y * ITEM + x] else 0) for x, px in enumerate(row)]
                for y, row in enumerate(self.rows)]
        return png_data_url(rgba)


def item_sample(shot: Shot, found: dict, slot: int) -> Item:
    """Item im Platz ausschneiden. Der Hintergrund ist der Rand direkt um das Item
    (dort liegt nie ein Item-Pixel); alles, was sich davon abhebt, gehoert zum Item."""
    s, x0, y0 = found["scale"], found["x0"], found["y0"]
    left = x0 + (3 + (slot - 1) * 20) * s
    top = y0 + 3 * s
    h = s // 2

    def at(gx, gy):
        return shot.rgb(left + gx * s + h, top + gy * s + h) or (0, 0, 0)

    ring = [at(i, -1) for i in range(-1, 17)] + [at(i, 16) for i in range(-1, 17)]
    ring += [at(-1, i) for i in range(ITEM)] + [at(16, i) for i in range(ITEM)]
    bg = tuple(sorted(c[k] for c in ring)[len(ring) // 2] for k in range(3))
    rows = [[at(gx, gy) for gx in range(ITEM)] for gy in range(ITEM)]
    mask = [_dist(rows[y][x], bg) > 45 for y in range(ITEM) for x in range(ITEM)]
    return Item(rows, mask, bg)


def mask_from_hex(text: str):
    try:
        bits = int(text, 16)
    except (TypeError, ValueError):
        return None
    return [bool(bits >> i & 1) for i in range(ITEM * ITEM)]


def similarity(a, b) -> float:
    """Wie aehnlich sind zwei Umrisse? (0–1, ohne die unteren Zeilen)"""
    n = MATCH_ROWS * ITEM
    both = sum(1 for i in range(n) if a[i] and b[i])
    either = sum(1 for i in range(n) if a[i] or b[i])
    return both / either if either else 0.0


def best_match(item: Item, masks) -> int:
    """Index des passenden angelernten Werkzeugs oder -1."""
    if item.empty:
        return -1
    best, best_i = 0.0, -1
    for i, m in enumerate(masks):
        if m is None:
            continue
        sim = similarity(item.mask, m)
        if sim > best:
            best, best_i = sim, i
    return best_i if best >= MATCH_IOU else -1


def png_data_url(rows) -> str:
    """Kleines PNG (RGB oder RGBA) als data:-URL – ohne Zusatzmodule."""
    return "data:image/png;base64," + base64.b64encode(png_bytes(rows)).decode("ascii")


def png_bytes(rows) -> bytes:
    h, w = len(rows), len(rows[0])
    channels = len(rows[0][0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    color = 6 if channels == 4 else 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def shot_png(shot: Shot) -> bytes:
    """Ganzer Ausschnitt als PNG (zur Fehlersuche: was hat der AutoClicker gesehen?)."""
    px = shot.pixels
    rows = []
    for y in range(shot.h):
        i = y * shot.w * 4
        line = px[i:i + shot.w * 4]
        rows.append([(line[x + 2], line[x + 1], line[x]) for x in range(0, len(line), 4)])
    return png_bytes(rows)
