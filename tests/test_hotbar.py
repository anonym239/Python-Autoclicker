import base64
import os
import random
import struct
import tempfile
import time
import unittest

from clicker.app import App
from clicker.backend import DemoBackend
from clicker.engine import ClickEngine, ClickSettings, SmartSettings
from clicker.hotbar import (CAPTURE_GUI_H, MAX_SCALE, Shot, SlotTracker, analyze, auto_gui_scale, best_match,
                            item_sample, locate, mask_from_hex, png_bytes, same_tool, shot_png)

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
                    rect(ix + x, hy + 3 + y, 1, 1, HANDLE if c == "H" else color)
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
        masks = [mask_from_hex(pick.mask_hex())]
        self.assertEqual(masks[0], pick.mask)

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
    import zlib
    with open(os.path.join(os.path.dirname(__file__), "data", "hypixel_hotbar.bin"), "rb") as f:
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
        pickaxe = [items[4].mask]
        self.assertEqual(best_match(items[4], pickaxe), 0)
        self.assertEqual(best_match(items[5], pickaxe), 0)   # Axt ist auch ein Werkzeug – darf passen
        for other in (1, 2, 3, 9):                            # Schwert, Eisen, Gold, Kompass: nie
            self.assertEqual(best_match(items[other], pickaxe), -1, other)
        # Spitzhacke und Axt sind beim Anlernen zwei verschiedene Eintraege
        self.assertEqual(same_tool(items[5], pickaxe), -1)
        self.assertEqual(same_tool(items[4], pickaxe), 0)
        # Icon: nur das Item, durchsichtiger Hintergrund (nicht das ganze Feld)
        self.assertLess(items[4].size, 100)


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
                self.assertFalse(st["engine"]["armed"])  # Anlernen schaltet den Klicker aus

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
                self.assertEqual(app.notice["key"], "n_tool_saved")
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
