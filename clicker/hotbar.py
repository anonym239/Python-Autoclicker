"""Werkzeug-Erkennung fuer Minecraft PvP / CPS-Boost (plattformunabhaengig).

Idee: Mit Werkzeug (Spitzhacke, Axt, Schere ...) in der Hand soll die Maustaste
normal gehalten werden – sonst kann man z. B. bei BedWars das Bett nicht abbauen.
Minecraft verraet anderen Programmen nicht, was man in der Hand haelt (und das
Spiel auszulesen waere ein Hack). Deshalb:

- SlotTracker merkt sich den gewaehlten Hotbar-Platz (Tasten 1–9, Mausrad).
- analyze() erkennt den Platz zusaetzlich auf einem Bildschirmausschnitt der
  Hotbar (heller Auswahlrahmen) und schneidet das Item als kleines Bild aus.
- Beim "Anlernen" wird der Platz des Werkzeugs gespeichert, samt Bild als Icon.
"""

from __future__ import annotations

import base64
import struct
import zlib

SLOTS = 9
HOTBAR_W, HOTBAR_H = 182, 22  # Minecraft-GUI-Einheiten
CAPTURE_GUI_H = 24            # so viel vom unteren Rand wird gebraucht (Auswahlrahmen ragt 1 heraus)
MAX_SCALE = 8


class SlotTracker:
    """Gewaehlter Hotbar-Platz 1–9 aus Tasten und Mausrad.

    Bei offenem Chat / Inventar aendern Zifferntasten und Mausrad den Platz nicht."""

    def __init__(self):
        self.slot = 1
        self._screen = ""  # "" | "chat" | "inv"

    def key(self, name: str) -> bool:
        """Taste gedrueckt. -> True, wenn sich der Platz geaendert hat."""
        if self._screen == "chat":
            if name in ("enter", "esc"):
                self._screen = ""
            return False
        if self._screen == "inv":
            if name in ("e", "esc"):
                self._screen = ""
            return False
        if name in ("t", "slash"):
            self._screen = "chat"
        elif name == "e":
            self._screen = "inv"
        elif len(name) == 1 and name in "123456789":
            return self._set(int(name))
        return False

    def wheel(self, up: bool) -> bool:
        """Mausrad: hoch = Platz nach links, runter = nach rechts (wie in Minecraft)."""
        if self._screen:
            return False
        return self._set((self.slot - 1 + (-1 if up else 1)) % SLOTS + 1)

    def sync(self, slot: int) -> bool:
        """Platz wurde auf dem Bildschirm erkannt (dann ist auch kein Inventar offen)."""
        self._screen = ""
        return self._set(slot)

    def _set(self, slot: int) -> bool:
        changed = slot != self.slot
        self.slot = slot
        return changed


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
    """Hotbar suchen. -> dict(scale, slot 1–9, confidence) oder None.

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
        if top >= 150 and conf >= 45 and (best is None or conf > best["confidence"]):
            best = {"scale": s, "slot": order[0] + 1, "confidence": round(conf, 1), "x0": x0, "y0": y0}
    return best


def item_pixels(shot: Shot, found: dict, slot: int):
    """Das Item im Platz als 16x16 RGB-Pixel (Zeilen)."""
    s, x0, y0 = found["scale"], found["x0"], found["y0"]
    left = x0 + (3 + (slot - 1) * 20) * s
    top = y0 + 3 * s
    rows = []
    for gy in range(16):
        row = []
        for gx in range(16):
            row.append(shot.rgb(left + gx * s + s // 2, top + gy * s + s // 2) or (0, 0, 0))
        rows.append(row)
    return rows


def looks_empty(rows) -> bool:
    """Leerer Platz? (fast keine Farbunterschiede)"""
    lum = [_luma(p) for row in rows for p in row]
    mean = sum(lum) / len(lum)
    return sum(abs(v - mean) for v in lum) / len(lum) < 6


def png_data_url(rows) -> str:
    """Kleines PNG (RGB) als data:-URL – ohne Zusatzmodule."""
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
