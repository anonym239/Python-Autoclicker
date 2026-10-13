import base64
import json
import os
import random
import struct
import tempfile
import time
import unittest

from clicker.app import App
from clicker.backend import DemoBackend
from clicker.engine import ClickEngine, ClickSettings, SmartSettings
from clicker.hotbar import (CAPTURE_GUI_H, MAX_SCALE, Shot, SlotTracker, analyze, auto_gui_scale,
                            best_match, item_sample, locate, mask_from_hex, merge_items, png_bytes, same_tool,
                            shot_png, slot_photo, template_from_icon)

WORLD = (90, 130, 200)
HOTBAR = (55, 55, 55)
FRAME = (235, 235, 235)
HANDLE = (105, 75, 40)
DIAMOND, IRON, GOLD = (70, 220, 210), (215, 215, 215), (250, 220, 60)

# Eigene, grobe Umrisse (keine Minecraft-Grafiken): Spitzhacke, Schwert, Wolle
PICKAXE = (["....XXXXXXX.....", "..XXX.....XXX...", ".XX.......H.XX..", "XX.......H....XX",
            "X.......H......X", "X......H........", "......H.........", ".....H.........."]
           + ["....H...........", "...H............", "..H.............", ".H..............",
              "H...............", "................", "................", "................"])
SWORD = ["..............XX", ".............XXX", "............XXX.", "...........XXX..",
         "..........XXX...", ".........XXX....", "........XXX.....", ".......XXX......",
         "..X...XXX.......", "...X.XXX........", "....XXX.........", "...HXX..........",
         "..H..X..........", ".H..............", "H...............", "................"]
WOOL = ["XXXXXXXXXXXXXXXX"] * 14 + ["................"] * 2
AXE = ["......XXXX......", ".....XXXXXX.....", "....XXXXXXX.....", "....XXXXXXH.....",
       ".....XXXXH......", "........H.......", ".......H........", "......H.........",
       ".....H..........", "....H...........", "...H............", "..H.............",
       ".H..............", "H...............", "................", "................"]
SHEARS = ["..........XX....", ".........XXX....", "........XXX.....", ".......XXX....XX",
          "......XXX....XXX", ".....XXX....XXX.", "....XXXX...XXX..", "....XX.XXXXXX...",
          "...HHH..XXXX....", "..HHHHH.........", ".HH...HH........", ".HH...HH........",
          "..HHHHH.........", "...HHH..........", "................", "................"]
NETHERITE, SHEAR_RED = (75, 60, 75), (200, 40, 40)
WOOD = (160, 120, 70)


def fake_hotbar(width, height, selected, items=None, scale=None, frame=True, see_through=False,
                slot_lines=False):
    """Unteren Bildschirmrand mit einer Minecraft-artigen Hotbar nachbauen (BGRA).

    items: {platz: (umriss, farbe)}"""
    s = scale or auto_gui_scale(width, height)
    rows = CAPTURE_GUI_H * MAX_SCALE
    top = height - rows
    px = bytearray(bytes((WORLD[2], WORLD[1], WORLD[0], 255)) * (width * rows))

    def rect(gx, gy, gw, gh, rgb):
        for y in range(gy * s, (gy + gh) * s):
            yy = y - top
            if 0 <= yy < rows:
                for x in range(gx * s, (gx + gw) * s):
                    if 0 <= x < width:
                        i = (yy * width + x) * 4
                        px[i:i + 4] = bytes((rgb[2], rgb[1], rgb[0], 255))

    gw, gh = -(-width // s), -(-height // s)
    hx, hy = gw // 2 - 91, gh - 22
    rect(hx, hy, 182, 22, HOTBAR)
    if see_through:  # durchsichtige Hotbar (Lunar Client): Gras schimmert unruhig durch
        rnd = random.Random(selected)
        for gy in range(1, 21):
            for gx in range(1, 181):
                v = rnd.randint(-12, 12)
                rect(hx + gx, hy + gy, 1, 1, (78 + v, 86 + v, 34 + v // 2))
    if slot_lines:  # hellere Linie direkt um jedes Item-Feld (wie bei manchen Hotbars)
        for i in range(9):
            ix = hx + 3 + i * 20
            rect(ix - 1, hy + 2, 18, 1, (120, 120, 120))
            rect(ix - 1, hy + 19, 18, 1, (120, 120, 120))
            rect(ix - 1, hy + 2, 1, 18, (120, 120, 120))
            rect(ix + 16, hy + 2, 1, 18, (120, 120, 120))
    fx = hx - 1 + (selected - 1) * 20
    if frame:
        rect(fx, hy - 1, 24, 2, FRAME)          # oben
        rect(fx, hy - 1, 2, 24, FRAME)          # links
        rect(fx + 22, hy - 1, 2, 24, FRAME)     # rechts
    for slot, (shape, color) in (items or {}).items():
        ix = hx + 3 + (slot - 1) * 20
        for y, line in enumerate(shape):
            for x, c in enumerate(line):
                if c != ".":
                    # Schattierung wie bei echten Items: Kanten oben hell, rechts dunkel –
                    # haengt nur von der Form ab, nicht vom Material
                    above = y > 0 and shape[y - 1][x] != "."
                    right = x < 15 and line[x + 1] != "."
                    f = 1.3 if not above else 0.7 if not right else 1.0
                    base = HANDLE if c == "H" else color
                    rect(ix + x, hy + 3 + y, 1, 1, tuple(min(255, int(v * f)) for v in base))
    return width, rows, bytes(px), height


def shot_of(*args, **kw):
    w, h, px, ch = fake_hotbar(*args, **kw)
    return Shot(w, h, px, ch)


class HotbarTests(unittest.TestCase):
    def test_auto_scale(self):
        self.assertEqual(auto_gui_scale(1920, 1080), 4)
        self.assertEqual(auto_gui_scale(1280, 720), 3)
        self.assertEqual(auto_gui_scale(854, 480), 2)

    def test_finds_selected_slot(self):
        for w, h, sel in ((1920, 1080, 1), (1280, 720, 5), (854, 480, 9), (1600, 900, 3)):
            found = analyze(shot_of(w, h, sel), w)
            self.assertIsNotNone(found, (w, h))
            self.assertEqual(found["slot"], sel, (w, h))
            self.assertEqual(found["scale"], auto_gui_scale(w, h))

    def test_fixed_gui_scale(self):
        found = analyze(shot_of(1920, 1080, 7, scale=2), 1920)
        self.assertEqual((found["scale"], found["slot"]), (2, 7))

    def test_nothing_found_without_hotbar(self):
        shot = Shot(800, 100, bytes((10, 200, 30, 255)) * 80000, 600)
        self.assertIsNone(analyze(shot, 800))

    def test_same_tool_any_slot_any_material(self):
        learned = shot_of(1280, 720, 2, {2: (PICKAXE, DIAMOND), 3: (SWORD, IRON)})
        found = analyze(learned, 1280)
        pick = item_sample(learned, found, 2)
        self.assertFalse(pick.empty)
        self.assertEqual(mask_from_hex(pick.mask_hex()), pick.mask)
        masks = [template_from_icon(pick.icon())]   # so wird es nach dem Speichern geladen

        # Andere Hotbar: Gold-Spitzhacke auf Platz 7, Schwert auf 1, Wolle auf 4, Platz 9 leer
        play = shot_of(1920, 1080, 7, {7: (PICKAXE, GOLD), 1: (SWORD, DIAMOND), 4: (WOOL, IRON)})
        found = analyze(play, 1920)
        self.assertEqual(best_match(item_sample(play, found, 7), masks), 0)
        self.assertEqual(best_match(item_sample(play, found, 1), masks), -1)
        self.assertEqual(best_match(item_sample(play, found, 4), masks), -1)
        empty = item_sample(play, found, 9)
        self.assertTrue(empty.empty)
        self.assertEqual(best_match(empty, masks), -1)

    def test_icon_is_transparent_png(self):
        shot = shot_of(1280, 720, 4, {4: (PICKAXE, DIAMOND)})
        item = item_sample(shot, analyze(shot, 1280), 4)
        url = item.icon()
        png = base64.b64decode(url.split(",", 1)[1])
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        w, h, depth, color = struct.unpack(">IIBB", png[16:26])
        self.assertEqual((w, h, depth, color), (16, 16, 8, 6))  # RGBA
        self.assertLess(len(url), 8000)
        self.assertEqual(shot_png(shot)[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png_bytes([[(1, 2, 3)]])[:8], b"\x89PNG\r\n\x1a\n")


def real_hypixel_shot():
    """Echte Aufnahme (Hypixel BedWars, Lunar Client, Texture Pack mit hellen Platz-Raendern):
    1 Holzschwert, 2 Eisen, 3 Gold, 4 Eisen-Spitzhacke (verzaubert, gewaehlt),
    5 Eisen-Axt (verzaubert), 6–8 leer, 9 Kompass."""
    return _real_shot("hypixel_hotbar.bin")


def real_server_shot():
    """Echte Aufnahme (anderer Server, Texture Pack mit animierten gruenen Ranken hinter der
    Hotbar): 1 Diamant-Schwert, 2 Diamant-Spitzhacke, 3 Diamant-Axt, 4 Diamant-Schaufel,
    5 Eimer, 6 Bruchstein, 7 Lachs, 8 Enderperlen, 9 leer (gewaehlt)."""
    return _real_shot("server_hotbar.bin")


def _real_shot(name):
    import zlib
    with open(os.path.join(os.path.dirname(__file__), "data", name), "rb") as f:
        blob = f.read()
    w, h, x0, y0, cw, ch = struct.unpack(">6I", blob[:24])
    crop = zlib.decompress(blob[24:])
    rows = CAPTURE_GUI_H * MAX_SCALE
    px = bytearray(w * rows * 4)
    for y in range(ch):
        i = ((y0 + y - (h - rows)) * w + x0) * 4
        px[i:i + cw * 4] = crop[y * cw * 4:(y + 1) * cw * 4]
    return Shot(w, rows, bytes(px), h)


class RealScreenshotTests(unittest.TestCase):
    def test_hypixel_hotbar(self):
        shot = real_hypixel_shot()
        found = analyze(shot, 1280)
        self.assertEqual((found["slot"], found["scale"]), (4, 3))
        items = {i: item_sample(shot, found, i) for i in range(1, 10)}
        for empty in (6, 7, 8):
            self.assertTrue(items[empty].empty, empty)
        tools = [template_from_icon(items[4].icon()), template_from_icon(items[5].icon())]
        self.assertEqual(best_match(items[4], tools), 0)
        self.assertEqual(best_match(items[5], tools), 1)
        for other in (1, 2, 3, 6, 7, 8, 9):                   # Schwert, Eisen, Gold, leer, Kompass: nie
            self.assertEqual(best_match(items[other], tools), -1, other)
        # Spitzhacke und Axt sind beim Anlernen zwei verschiedene Eintraege
        self.assertEqual(same_tool(items[5], tools[:1]), -1)
        self.assertEqual(same_tool(items[4], tools[:1]), 0)
        # Icon: nur das Item, durchsichtiger Hintergrund (nicht das ganze Feld)
        self.assertLess(items[4].size, 100)


    def test_other_server_other_pack_other_material(self):
        """Angelernt auf Hypixel (Eisen, verzaubert) -> erkannt auf anderem Server (Diamant,
        anderes Texture Pack mit animiertem Hintergrund) – und umgekehrt."""
        hyp, srv = real_hypixel_shot(), real_server_shot()
        fh, fs = analyze(hyp, 1280), analyze(srv, 1280)
        self.assertEqual((fs["slot"], fs["scale"]), (9, 3))
        h = {i: item_sample(hyp, fh, i) for i in range(1, 10)}
        s = {i: item_sample(srv, fs, i) for i in range(1, 10)}
        tools = [template_from_icon(h[4].icon()), template_from_icon(h[5].icon())]   # Spitzhacke, Axt
        self.assertEqual(best_match(s[2], tools), 0)
        self.assertEqual(best_match(s[3], tools), 1)
        for other in (1, 4, 5, 6, 7, 8, 9):   # Schwert, Schaufel (nicht angelernt), Eimer, Stein, ...
            self.assertEqual(best_match(s[other], tools), -1, other)
        back = [template_from_icon(s[2].icon()), template_from_icon(s[3].icon())]
        self.assertEqual(best_match(h[4], back), 0)
        self.assertEqual(best_match(h[5], back), 1)
        for other in (1, 2, 3, 9):
            self.assertEqual(best_match(h[other], back), -1, other)

    def test_pickaxes_of_different_material_are_kept_apart(self):
        """Eisen- (Hypixel) und Diamant-Spitzhacke (anderer Server) haben fast dasselbe
        Hell-Dunkel-Muster – beim Anlernen sind es trotzdem zwei Eintraege. Dasselbe Item
        nochmal ersetzt den alten Eintrag. Mit allen vier Werkzeugen bleibt der Rest frei."""
        hyp, srv = real_hypixel_shot(), real_server_shot()
        fh, fs = analyze(hyp, 1280), analyze(srv, 1280)
        h = {i: item_sample(hyp, fh, i) for i in range(1, 10)}
        s = {i: item_sample(srv, fs, i) for i in range(1, 10)}
        tools = []
        for item in (h[4], s[2], h[5], s[3]):   # Eisen-Spitzhacke, Diamant-Spitzhacke, Eisen-Axt, Diamant-Axt
            self.assertEqual(same_tool(item, tools), -1)
            tools.append(template_from_icon(item.icon()))
        self.assertEqual(same_tool(h[4], tools), 0)
        self.assertEqual(same_tool(s[3], tools), 3)
        for item in (h[4], s[2], h[5], s[3]):
            self.assertGreaterEqual(best_match(item, tools), 0)
        for other in (h[1], h[2], h[3], h[9], s[1], s[5], s[6], s[7], s[8], s[9]):
            self.assertEqual(best_match(other, tools), -1)

    def test_animated_background_is_removed_when_learning(self):
        srv = real_server_shot()
        found = analyze(srv, 1280)
        axe = item_sample(srv, found, 3)
        # zweite "Aufnahme": Ranken haben sich bewegt -> andere Hintergrund-Pixel
        noisy = item_sample(srv, found, 3)
        noisy.mask = list(noisy.mask)
        moved = [i for i in range(256) if not axe.mask[i] and 16 < i < 200][::7]
        for i in moved:
            noisy.mask[i] = True
        merged = merge_items([axe, noisy])
        self.assertLessEqual(merged.size, axe.size)


    def test_slot_photo_is_one_to_one(self):
        shot = real_server_shot()
        found = analyze(shot, 1280)
        url = slot_photo(shot, found, 2)
        png = base64.b64decode(url.split(",", 1)[1])
        self.assertEqual(struct.unpack(">II", png[16:24]), (60, 60))   # 20 GUI-Pixel x 3
        self.assertLess(len(url), 40000)


class FallbackTests(unittest.TestCase):
    def test_tracker(self):
        t = SlotTracker()
        t.key("3")
        t.wheel(up=False)
        self.assertEqual(t.slot, 4)
        t.key("1")
        t.wheel(up=True)
        self.assertEqual(t.slot, 9)
        t.key("t")
        t.key("5")             # im Chat getippt
        t.key("enter")
        t.key("e")             # Inventar
        t.key("2")
        t.wheel(up=False)
        self.assertEqual(t.slot, 9)
        t.key("esc")
        t.key("2")
        self.assertEqual(t.slot, 2)

    def test_locate_without_frame_uses_guess(self):
        shot = shot_of(1280, 720, 6, {6: (PICKAXE, IRON)}, frame=False)
        self.assertIsNone(analyze(shot, 1280))
        found = locate(shot, 1280, 6)
        self.assertFalse(found["sure"])
        self.assertEqual((found["slot"], found["scale"]), (6, 3))
        self.assertFalse(item_sample(shot, found, 6).empty)
        sure = locate(shot_of(1280, 720, 2), 1280, 6)
        self.assertTrue(sure["sure"])
        self.assertEqual(sure["slot"], 2)


class ToolEngineTests(unittest.TestCase):
    def setUp(self):
        self.backend = DemoBackend()
        self.engine = ClickEngine(self.backend)
        self.engine.configure(ClickSettings(mode="hold_mouse", cps_min=40, cps_max=40), SmartSettings())
        self.engine.start_threads()

    def tearDown(self):
        self.engine.shutdown()

    def test_tool_in_hand_holds_instead_of_clicking(self):
        self.engine.start()
        self.engine.set_tool(True)
        self.engine.set_mouse_held("left", True)
        time.sleep(0.3)
        self.assertEqual(self.backend.clicks, 0)
        self.assertEqual(self.engine.status()["state"], "ready")
        self.assertTrue(self.engine.status()["tool"])
        # Schwert genommen -> wieder schnelle Klicks
        self.engine.set_tool(False)
        time.sleep(0.3)
        self.assertGreater(self.backend.clicks, 3)
        # Werkzeug waehrend des Haltens -> Taste wird im Spiel wieder gedrueckt
        self.engine.set_tool(True)
        self.assertIn("left", self.backend.down)

    def test_waits_briefly_for_the_check(self):
        self.engine.start()
        self.engine.begin_tool_check(5.0)
        self.engine.set_mouse_held("left", True)
        time.sleep(0.2)
        self.assertEqual(self.backend.clicks, 0)   # noch nicht entschieden
        self.engine.set_tool(False)                 # kein Werkzeug -> los
        time.sleep(0.2)
        self.assertGreater(self.backend.clicks, 3)


class LearnTests(unittest.TestCase):
    def wait_for(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_learn_in_creative_and_detect_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.start()
            screen = app.backend
            try:
                app.engine.start()
                st = app.tools_action({"op": "learn"})
                self.assertTrue(st["learning"])
                self.assertTrue(st["engine"]["armed"])   # Anlernen schaltet NICHT aus ...
                self.assertTrue(self.wait_for(lambda: app.engine.status()["state"] == "paused"))  # ... pausiert nur

                # Hotbar nicht sichtbar -> Hinweis, Anlernen laeuft weiter
                app._on_mouse("left", True)
                app._on_mouse("left", False)
                self.assertTrue(self.wait_for(lambda: app.notice and app.notice["key"] == "e_hotbar"))
                self.assertTrue(app.learning)
                self.assertEqual(app.state()["learn_error"], "e_hotbar")
                self.assertIn("learn_fail", screen.beeps)

                # Kreativmodus: kurzer Klick genuegt
                screen.screen = fake_hotbar(1280, 720, 3, {3: (PICKAXE, DIAMOND), 1: (SWORD, IRON)})
                app._on_mouse("left", True)
                app._on_mouse("left", False)
                self.assertTrue(self.wait_for(lambda: not app.learning))
                tools = app.config.tools()
                self.assertEqual(len(tools), 1)
                self.assertTrue(tools[0]["icon"].startswith("data:image/png;base64,"))
                self.assertTrue(tools[0]["photo"].startswith("data:image/png;base64,"))  # Platz 1:1
                self.assertEqual(app.notice["key"], "n_tool_saved")
                self.assertTrue(app.engine.armed)          # nach dem Anlernen laeuft er einfach weiter
                self.assertTrue(self.wait_for(lambda: app.engine.status()["state"] != "paused"))
                self.assertTrue(os.path.isfile(os.path.join(tmp, "hotbar-aufnahme.png")))

                # Gleiches Werkzeug nochmal anlernen -> ersetzt statt doppelt
                app.tools_action({"op": "learn"})
                app._on_mouse("left", True)
                app._on_mouse("left", False)
                self.assertTrue(self.wait_for(lambda: not app.learning))
                self.assertEqual(len(app.config.tools()), 1)

                # PvP: Werkzeug auf einem ganz anderen Platz / anderes Material
                app.handle("preset", {"id": "pvp"})
                app.engine.start()
                screen.screen = fake_hotbar(1920, 1080, 8, {8: (PICKAXE, GOLD), 2: (SWORD, DIAMOND)})
                app._on_mouse("left", True)
                self.assertTrue(self.wait_for(lambda: app.engine.tool))
                self.assertEqual(app.tool_index, 0)
                app._on_mouse("left", False)

                # Schwert -> nicht eingeschraenkt
                screen.screen = fake_hotbar(1920, 1080, 2, {8: (PICKAXE, GOLD), 2: (SWORD, DIAMOND)})
                app._on_mouse("left", True)
                self.assertTrue(self.wait_for(lambda: not app.engine.tool))
                # waehrend gehalten wird auf leeren Platz gewechselt -> bleibt frei
                screen.screen = fake_hotbar(1920, 1080, 5, {8: (PICKAXE, GOLD)})
                time.sleep(0.3)
                self.assertFalse(app.engine.tool)
                # ... und auf die Spitzhacke -> wird erkannt, ohne loszulassen
                screen.screen = fake_hotbar(1920, 1080, 8, {8: (PICKAXE, GOLD)})
                self.assertTrue(self.wait_for(lambda: app.engine.tool))
                app._on_mouse("left", False)

                # Hotbar gar nicht zu sehen -> nie einschraenken
                screen.screen = None
                app._on_mouse("left", True)
                self.assertTrue(self.wait_for(lambda: not app.engine.tool))
                app._on_mouse("left", False)

                st = app.tools_action({"op": "delete", "index": 0})
                self.assertEqual(st["config"]["tools"], [])
                self.assertEqual(app.tools_action({"op": "delete", "index": 0}), {"error": "e_not_found"})
            finally:
                app.shutdown()

    def test_learn_without_frame_by_keys(self):
        """Texture Pack ohne erkennbaren Auswahlrahmen: Platz kommt von den Tasten."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.backend.screen = fake_hotbar(1280, 720, 4, {4: (PICKAXE, IRON), 1: (SWORD, IRON)}, frame=False)
            app.tools_action({"op": "learn"})
            app._on_raw_input("k", "4", True)
            app._on_mouse("left", True)
            app._on_mouse("left", False)
            self.assertTrue(self.wait_for(lambda: not app.learning))
            self.assertEqual(len(app.config.tools()), 1)
            self.assertIn("learn_ok", app.backend.beeps)
            with open(os.path.join(tmp, "hotbar-log.txt"), encoding="utf-8") as f:
                self.assertIn("Rahmen NICHT erkannt", f.read())

    def test_learn_by_hotkey_with_tool_already_in_hand(self):
        """Anlern-Hotkey: das Werkzeug ist schon gewaehlt, BEVOR das Anlernen startet
        (leeres Kit, kein erkennbarer Auswahlrahmen) -> trotzdem der richtige Platz."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.backend.screen = fake_hotbar(1280, 720, 4, {4: (PICKAXE, IRON), 1: (SWORD, IRON)}, frame=False)
            app.handle("preset", {"id": "pvp"})
            app.handle("settings", {"general": {"learn_hotkey_on": True}})
            app._on_raw_input("k", "4", True)       # im Spiel Platz 4 gewaehlt
            app._on_hotkey("learn", True)           # dann F7
            self.assertTrue(app.learning)
            app._on_mouse("left", True)
            app._on_mouse("left", False)
            self.assertTrue(self.wait_for(lambda: not app.learning))
            self.assertEqual(len(app.config.tools()), 1)
            self.assertIn("learn_ok", app.backend.beeps)
            shot, found = app._grab_hotbar()
            self.assertEqual(best_match(item_sample(shot, found, 4), app._tool_templates), 0)   # Spitzhacke
            self.assertEqual(best_match(item_sample(shot, found, 1), app._tool_templates), -1)  # nicht das Schwert

    def test_learn_many_materials_all_kept(self):
        """Volle Hotbar: Holz-, Diamant-, Netherite-, Eisen- und Gold-Spitzhacke plus zwei Aexte
        nacheinander anlernen -> alle bleiben einzeln gespeichert (nichts wird ueberschrieben).
        Danach: jedes Werkzeug bremst, Schwert und Wolle nie."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.start()
            screen = app.backend
            items = {1: (SWORD, DIAMOND), 2: (PICKAXE, WOOD), 3: (PICKAXE, DIAMOND), 4: (PICKAXE, NETHERITE),
                     5: (PICKAXE, IRON), 6: (PICKAXE, GOLD), 7: (AXE, IRON), 8: (AXE, DIAMOND), 9: (WOOL, IRON)}
            try:
                app.handle("preset", {"id": "pvp"})
                for slot in (2, 3, 4, 5, 6, 7, 8, 3):   # die Diamant-Spitzhacke am Ende nochmal
                    screen.screen = fake_hotbar(1280, 720, slot, items, see_through=True, slot_lines=True)
                    app.tools_action({"op": "learn"})
                    app._on_mouse("left", True)
                    app._on_mouse("left", False)
                    self.assertTrue(self.wait_for(lambda: not app.learning), slot)
                self.assertEqual(len(app.config.tools()), 7)   # die doppelte ersetzt, nicht hinzugefuegt

                app.engine.start()
                for slot in range(1, 10):
                    want = 2 <= slot <= 8
                    screen.screen = fake_hotbar(1280, 720, slot, items, see_through=True, slot_lines=True)
                    app._on_mouse("left", True)
                    self.assertTrue(self.wait_for(lambda: app.engine.tool == want and (app.tool_index >= 0) == want),
                                    (slot, app.tool_index))
                    app._on_mouse("left", False)
            finally:
                app.shutdown()

    def test_learn_three_tools_on_see_through_hotbar(self):
        """Lunar Client: durchsichtige Hotbar, drei Werkzeuge nacheinander -> drei Eintraege."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.start()
            screen = app.backend
            items = {5: (PICKAXE, NETHERITE), 6: (AXE, NETHERITE), 7: (SHEARS, SHEAR_RED), 8: (WOOL, IRON)}
            try:
                for slot in (5, 6, 7):
                    app.tools_action({"op": "learn"})
                    # "Zurueck zum Spiel" im Pause-Menue (Zeiger sichtbar) zaehlt nicht
                    screen.cursor = True
                    screen.screen = fake_hotbar(1280, 720, slot, items, see_through=True, slot_lines=True)
                    app._on_mouse("left", True)
                    app._on_mouse("left", False)
                    time.sleep(0.15)
                    self.assertTrue(app.learning)
                    screen.cursor = False
                    app._on_mouse("left", True)
                    app._on_mouse("left", False)
                    self.assertTrue(self.wait_for(lambda: not app.learning))
                tools = app.config.tools()
                self.assertEqual(len(tools), 3)
                for t in tools:  # Hintergrund ist durchsichtig, nicht mitgezaehlt
                    self.assertLess(bin(int(t["mask"], 16)).count("1"), 80)

                app.handle("preset", {"id": "pvp"})
                app.engine.start()
                for slot, want in ((5, 0), (6, 1), (7, 2), (8, -1), (2, -1)):
                    screen.screen = fake_hotbar(1280, 720, slot, items, see_through=True, slot_lines=True)
                    app._on_mouse("left", True)
                    self.assertTrue(self.wait_for(lambda: app.tool_index == want and app.engine.tool == (want >= 0)),
                                    (slot, app.tool_index))
                    app._on_mouse("left", False)
            finally:
                app.shutdown()

    def test_export_and_import_tools(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp}):
            os.mkdir(os.path.join(tmp, "Downloads"))
            a = App(os.path.join(tmp, "a"), "web", demo=True, keep_alive=True)
            self.assertEqual(a.tools_action({"op": "export"}), {"error": "e_no_tools"})
            shot = real_server_shot()
            found = analyze(shot, 1280)
            for slot in (2, 3):
                item = item_sample(shot, found, slot)
                a.config.learn_tool(item.mask_hex(), item.icon(), -1, slot_photo(shot, found, slot))
            a.tools_action({"op": "kit_rename", "index": 0, "name": "Hypixel BedWars"})
            a.tools_action({"op": "export"})
            path = os.path.join(tmp, "Downloads", "AutoClicker-Hypixel-BedWars.json")
            self.assertEqual(a.last_export, path)
            self.assertEqual(a.notice["key"], "n_tools_exported")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["tools"]), 2)
            self.assertTrue(data["tools"][0]["photo"].startswith("data:image/png"))
            self.assertEqual(data["name"], "Hypixel BedWars")

            # Auf einem anderen PC / nach Neuinstallation einlesen
            b = App(os.path.join(tmp, "b"), "web", demo=True, keep_alive=True)
            st = b.tools_action({"op": "import", "data": data})
            self.assertEqual(len(st["config"]["tools"]), 2)
            self.assertEqual(b.notice["vars"], {"n": 2})
            self.assertEqual(st["config"]["kits"], [{"name": "Hypixel BedWars", "count": 2}])
            b.tools_action({"op": "kit_new", "name": "Skywars"})
            b.tools_action({"op": "import", "data": data})          # nochmal -> keine Doppelten
            self.assertEqual(len(b.config.tools()), 2)
            self.assertEqual(b.config.kit_index(), 0)               # vorhandenes Kit gewaehlt
            self.assertEqual(b.notice["vars"], {"n": 0})
            self.assertEqual(b.tools_action({"op": "import", "data": "quatsch"}), {"error": "e_import"})
            # importierte Werkzeuge werden erkannt
            b.handle("preset", {"id": "pvp"})
            self.assertEqual(best_match(item_sample(shot, found, 2), b._tool_templates), 0)

    def test_click_in_own_window_does_not_learn(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.backend.screen = fake_hotbar(1280, 720, 1, {1: (PICKAXE, IRON)})
            app.backend.foreground = "AutoClicker 6"
            app.tools_action({"op": "learn"})
            app._on_mouse("left", True)
            app._on_mouse("left", False)
            time.sleep(0.2)
            self.assertTrue(app.learning)
            self.assertEqual(app.config.tools(), [])
            app.tools_action({"op": "cancel"})
            self.assertFalse(app.learning)


if __name__ == "__main__":
    unittest.main()
