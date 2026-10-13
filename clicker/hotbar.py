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
- Beim Anlernen wird das Bild des Items gespeichert. Verglichen wird spaeter das
  Hell-Dunkel-Muster an genau den Pixeln, an denen das angelernte Werkzeug liegt:
  Holz-, Stein-, Eisen-, Gold-, Diamant- und Netherite-Werkzeuge sind in Minecraft
  dieselbe Zeichnung in anderen Farben – das Muster bleibt gleich. Der Hintergrund
  (durchsichtige Hotbar, animierte Texture Packs) spielt dabei keine Rolle.
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
MATCH_NCC = 0.7               # so aehnlich muss das Hell-Dunkel-Muster sein (= Werkzeug in der Hand)
SAME_NCC = 0.9                # beim Anlernen: so aehnlich = dasselbe Werkzeug nochmal (ersetzen)
MIN_TEMPLATE = 12             # so viele Item-Pixel braucht ein angelerntes Werkzeug mindestens


class SlotTracker:
    """Gewaehlter Hotbar-Platz 1–9 aus Tasten und Mausrad (falls der Auswahlrahmen
    auf dem Bild nicht erkannt wird, z. B. bei manchen Texture Packs).
    Bei offenem Chat / Inventar zaehlen Zifferntasten und Mausrad nicht."""

    def __init__(self):
        self.slot = 1
        self._screen = ""  # "" | "chat" | "inv"

    def key(self, name: str) -> None:
        if self._screen == "chat":
            if name in ("enter", "esc"):
                self._screen = ""
        elif self._screen == "inv":
            if name in ("e", "esc"):
                self._screen = ""
        elif name in ("t", "slash"):
            self._screen = "chat"
        elif name == "e":
            self._screen = "inv"
        elif len(name) == 1 and name in "123456789":
            self.slot = int(name)

    def wheel(self, up: bool) -> None:
        """Mausrad: hoch = Platz nach links, runter = nach rechts (wie in Minecraft)."""
        if not self._screen:
            self.slot = (self.slot - 1 + (-1 if up else 1)) % SLOTS + 1

    def sync(self, slot: int) -> None:
        """Platz wurde auf dem Bild erkannt (dann ist auch kein Inventar offen)."""
        self._screen = ""
        self.slot = slot


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


def _top_edge(shot: Shot, x0: int, y0: int, slot: int, s: int) -> float:
    """Wie stark hebt sich die Zeile direkt ueber der Hotbar von der Zeile darueber ab?

    Nur der Auswahlrahmen ragt 1 Pixel ueber die Hotbar – bei allen anderen
    Plaetzen sind beide Zeilen Spielwelt. Klappt mit jedem Texture Pack und
    jeder Rahmenfarbe."""
    left = x0 + (slot * 20 - 1) * s
    h = s // 2
    total = 0
    for i in range(2, 22):
        a = shot.rgb(left + i * s + h, y0 - s + h)
        b = shot.rgb(left + i * s + h, y0 - 2 * s + h)
        if a is None or b is None:
            return 0.0
        total += _dist(a, b)
    return total / 20


def analyze(shot: Shot, width: int):
    """Hotbar suchen. -> dict(scale, slot 1–9, confidence, x0, y0) oder None.

    Probiert alle GUI-Groessen. Gewaehlt wird der Platz, dessen Auswahlrahmen
    sich deutlich abhebt: zuerst ueber die Oberkante (robust), sonst ueber die
    Helligkeit des Rahmens."""
    best = None
    auto = auto_gui_scale(width, shot.client_h)
    for s in [auto] + [x for x in range(1, MAX_SCALE + 1) if x != auto]:
        if HOTBAR_W * s > width or CAPTURE_GUI_H * s > shot.h:
            continue
        if best is not None and best["scale"] == auto:
            break  # "Automatisch" passt – das ist fast immer richtig
        x0, y0 = _layout(width, shot.client_h, s)
        for score, need_top, need_gap in ((_top_edge, 60, 40), (_ring_brightness, 130, 35)):
            vals = [score(shot, x0, y0, i, s) for i in range(SLOTS)]
            order = sorted(range(SLOTS), key=lambda i: vals[i], reverse=True)
            top, gap = vals[order[0]], vals[order[0]] - vals[order[1]]
            if top >= need_top and gap >= need_gap:
                if best is None or gap > best["confidence"]:
                    best = {"scale": s, "slot": order[0] + 1, "confidence": round(gap, 1), "x0": x0, "y0": y0}
                break
    return best


def locate(shot: Shot, width: int, guess_slot: int):
    """Hotbar + gewaehlter Platz. Mit Auswahlrahmen -> sicher ("sure": True);
    sonst Annahme: GUI-Groesse "Automatisch" und der Platz aus Tasten/Mausrad."""
    found = analyze(shot, width)
    if found:
        return dict(found, sure=True)
    s = auto_gui_scale(width, shot.client_h)
    if HOTBAR_W * s > width or CAPTURE_GUI_H * s > shot.h:
        return None
    x0, y0 = _layout(width, shot.client_h, s)
    return {"scale": s, "slot": guess_slot, "confidence": 0.0, "x0": x0, "y0": y0, "sure": False}


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
    """Item im Platz ausschneiden und vom Hintergrund trennen.

    - Die aeusserste Pixelreihe des 16x16-Felds wird ignoriert: dort liegt bei vielen
      Texture Packs schon der (helle) Rand des Platzes, nie aber ein wichtiger Teil
      eines Werkzeugs.
    - Hintergrund = die naechsten zwei Reihen nach innen, die ein Werkzeug nur selten
      fuellt. Bei durchsichtiger Hotbar ist der Rand unruhiger – dann ist die
      Schwelle hoeher, damit die Welt dahinter nicht zum Item gezaehlt wird."""
    s, x0, y0 = found["scale"], found["x0"], found["y0"]
    left = x0 + (3 + (slot - 1) * 20) * s
    top = y0 + 3 * s
    h = s // 2

    def at(gx, gy):
        return shot.rgb(left + gx * s + h, top + gy * s + h) or (0, 0, 0)

    rows = [[at(gx, gy) for gx in range(ITEM)] for gy in range(ITEM)]
    edge = [rows[y][x] for y in range(1, 15) for x in range(1, 15)
            if x in (1, 2, 13, 14) or y in (1, 2, 13, 14)]
    bg = tuple(sorted(c[k] for c in edge)[len(edge) // 2] for k in range(3))
    spread = sorted(_dist(c, bg) for c in edge)[len(edge) * 2 // 5]
    limit = max(36, 2 * spread + 18)
    dists = [_dist(rows[y][x], bg) if 0 < x < 15 and 0 < y < 15 else 0 for y in range(ITEM) for x in range(ITEM)]
    mask = [d > limit for d in dists]
    # Duenne, dunkle Teile (z. B. Stiel auf dunklem Hintergrund): Nachbarn mit etwas
    # schwaecherem Unterschied gehoeren auch noch dazu
    for _ in range(3):
        grow = [not mask[i] and dists[i] > limit * 0.55 and any(
                    0 <= i % ITEM + dx < ITEM and 0 <= i // ITEM + dy < ITEM
                    and mask[i + dy * ITEM + dx] for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                for i in range(ITEM * ITEM)]
        if not any(grow):
            break
        mask = [m or g for m, g in zip(mask, grow)]
    return Item(rows, _drop_specks(_drop_bars(mask)), bg)


def _drop_bars(mask):
    """Haltbarkeitsbalken (waagrechte Linie ganz unten) gehoert nicht zum Item."""
    mask = list(mask)
    for y in (12, 13, 14):
        run = best = 0
        for x in range(ITEM):
            run = run + 1 if mask[y * ITEM + x] else 0
            best = max(best, run)
        if best >= 9:
            for x in range(ITEM):
                mask[y * ITEM + x] = False
    return mask


def _drop_specks(mask, smallest: int = 3):
    """Einzelne Stoerpixel (z. B. Ranken eines Texture Packs) entfernen: zusammenhaengende
    Gruppen mit weniger als `smallest` Pixeln fliegen raus (8er-Nachbarschaft)."""
    mask = list(mask)
    seen = set()
    for start in range(ITEM * ITEM):
        if not mask[start] or start in seen:
            continue
        group, todo = [], [start]
        seen.add(start)
        while todo:
            i = todo.pop()
            group.append(i)
            x, y = i % ITEM, i // ITEM
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    j = ny * ITEM + nx
                    if 0 <= nx < ITEM and 0 <= ny < ITEM and mask[j] and j not in seen:
                        seen.add(j)
                        todo.append(j)
        if len(group) < smallest:
            for i in group:
                mask[i] = False
    return mask


def merge_items(items):
    """Mehrere Aufnahmen desselben Platzes: nur was in allen gleich aussieht, ist Item.
    Ein animierter Hintergrund (Texture Pack) faellt so heraus."""
    first = items[0]
    if len(items) == 1:
        return first
    mask = [all(it.mask[i] for it in items)
            and all(_dist(it.rows[i // ITEM][i % ITEM], first.rows[i // ITEM][i % ITEM]) < 60 for it in items)
            for i in range(ITEM * ITEM)]
    merged = Item(first.rows, _drop_specks(mask), first.bg)
    return merged if merged.size >= MIN_ITEM_PIXELS else first


def mask_from_hex(text: str):
    try:
        bits = int(text, 16)
    except (TypeError, ValueError):
        return None
    return [bool(bits >> i & 1) for i in range(ITEM * ITEM)]


class Template:
    """Angelerntes Werkzeug: an welchen Pixeln es liegt und wie hell sie sind."""

    def __init__(self, mask, lum):
        idx = [y * ITEM + x for y in range(1, MATCH_ROWS) for x in range(1, ITEM - 1) if mask[y * ITEM + x]]
        self.idx = idx
        vals = [lum[i] for i in idx]
        self.mean = sum(vals) / len(vals) if vals else 0.0
        self.dev = [v - self.mean for v in vals]
        self.norm = sum(d * d for d in self.dev) ** 0.5

    @property
    def usable(self) -> bool:
        return len(self.idx) >= MIN_TEMPLATE and self.norm > 1e-6

    @classmethod
    def from_item(cls, item: "Item") -> "Template":
        return cls(item.mask, [_luma(px) for row in item.rows for px in row])

    def score(self, item: "Item") -> float:
        """Korrelation des Hell-Dunkel-Musters (−1 … 1) an den Pixeln des Werkzeugs."""
        if not self.usable:
            return 0.0
        vals = [_luma(item.rows[i // ITEM][i % ITEM]) for i in self.idx]
        mean = sum(vals) / len(vals)
        dv = [v - mean for v in vals]
        norm = sum(d * d for d in dv) ** 0.5
        if norm < 1e-6:
            return 0.0
        return sum(a * b for a, b in zip(self.dev, dv)) / (self.norm * norm)


def template_from_icon(url: str):
    """Template aus dem gespeicherten Icon (PNG mit Alpha = Item-Pixel) – so muss nach
    einem Update nichts neu angelernt werden."""
    rows = png_read_rgba(url)
    if not rows or len(rows) != ITEM or any(len(r) != ITEM for r in rows):
        return None
    mask = [rows[y][x][3] > 127 for y in range(ITEM) for x in range(ITEM)]
    lum = [_luma(rows[y][x][:3]) for y in range(ITEM) for x in range(ITEM)]
    t = Template(mask, lum)
    return t if t.usable else None


def best_match(item: Item, templates) -> int:
    """Index des passenden angelernten Werkzeugs oder -1."""
    best, best_i = MATCH_NCC, -1
    for i, t in enumerate(templates):
        if t is None:
            continue
        sc = t.score(item)
        if sc >= best:
            best, best_i = sc, i
    return best_i


def same_tool(item: Item, templates) -> int:
    """Beim Anlernen: Index desselben Werkzeugs (wird ersetzt) oder -1."""
    for i, t in enumerate(templates):
        if t is not None and t.score(item) >= SAME_NCC:
            return i
    return -1


def png_read_rgba(url: str):
    """Unsere eigenen kleinen PNGs (RGBA, Filter 0) wieder einlesen."""
    try:
        data = base64.b64decode(url.split(",", 1)[1])
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos, idat, w = 8, b"", 0
        while pos < len(data):
            n = struct.unpack(">I", data[pos:pos + 4])[0]
            kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
            if kind == b"IHDR":
                w, h, depth, color = struct.unpack(">IIBB", body[:10])
                if depth != 8 or color != 6:
                    return None
            elif kind == b"IDAT":
                idat += body
            pos += 12 + n
        raw = zlib.decompress(idat)
        stride = 1 + w * 4
        rows = []
        for y in range(h):
            line = raw[y * stride:(y + 1) * stride]
            if line[0] != 0:
                return None
            rows.append([tuple(line[1 + x * 4:5 + x * 4]) for x in range(w)])
        return rows
    except Exception:
        return None


def slot_photo(shot: Shot, found: dict, slot: int, margin: int = 2) -> str:
    """Foto des Hotbar-Platzes 1:1 wie im Spiel (mit Hintergrund des Texture Packs) –
    nur zum Anzeigen. Bis zu 3 Bildschirmpixel pro GUI-Pixel, damit die Datei klein bleibt."""
    s, x0, y0 = found["scale"], found["x0"], found["y0"]
    step = max(1, s // 3)
    left = x0 + (3 - margin + (slot - 1) * 20) * s
    top = y0 + (3 - margin) * s
    size = (ITEM + 2 * margin) * s
    rows = []
    for y in range(top + step // 2, top + size, step):
        row = []
        for x in range(left + step // 2, left + size, step):
            row.append(shot.rgb(x, y) or (0, 0, 0))
        rows.append(row)
    return png_data_url(rows)


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
