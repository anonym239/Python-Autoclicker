import base64
import struct
import tempfile
import time
import unittest
import zlib

from clicker.app import App
from clicker.backend import DemoBackend
from clicker.engine import ClickEngine, ClickSettings, SmartSettings
from clicker.hotbar import (CAPTURE_GUI_H, MAX_SCALE, Shot, SlotTracker, analyze, auto_gui_scale,
                            item_pixels, looks_empty, png_data_url)

WORLD = (90, 130, 200)
HOTBAR = (55, 55, 55)
FRAME = (235, 235, 235)


def fake_hotbar(width, height, selected, scale=None, item_slot=None):
    """Unteren Bildschirmrand mit einer Minecraft-Hotbar nachbauen (BGRA)."""
    s = scale or auto_gui_scale(width, height)
    rows = CAPTURE_GUI_H * MAX_SCALE
    top = height - rows
    px = bytearray(bytes((WORLD[2], WORLD[1], WORLD[0], 255)) * (width * rows))

    def put(x, y, rgb):
        yy = y - top
        if 0 <= x < width and 0 <= yy < rows:
            i = (yy * width + x) * 4
            px[i:i + 4] = bytes((rgb[2], rgb[1], rgb[0], 255))

    def rect(gx, gy, gw, gh, rgb):
        for y in range(gy * s, (gy + gh) * s):
            for x in range(gx * s, (gx + gw) * s):
                put(x, y, rgb)

    gw, gh = -(-width // s), -(-height // s)
    hx, hy = gw // 2 - 91, gh - 22
    rect(hx, hy, 182, 22, HOTBAR)
    fx = hx - 1 + (selected - 1) * 20
    rect(fx, hy - 1, 24, 2, FRAME)          # oben
    rect(fx, hy - 1, 2, 24, FRAME)          # links
    rect(fx + 22, hy - 1, 2, 24, FRAME)     # rechts
    if item_slot:
        ix = hx + 3 + (item_slot - 1) * 20
        for gy in range(16):
            for gx in range(16):
                rect(ix + gx, hy + 3 + gy, 1, 1, (200, 40, 40) if (gx + gy) % 2 else (240, 200, 60))
    return Shot(width, rows, bytes(px), height)


class HotbarTests(unittest.TestCase):
    def test_auto_scale(self):
        self.assertEqual(auto_gui_scale(1920, 1080), 4)
        self.assertEqual(auto_gui_scale(1280, 720), 3)
        self.assertEqual(auto_gui_scale(854, 480), 2)

    def test_finds_selected_slot(self):
        for w, h, sel in ((1920, 1080, 1), (1280, 720, 5), (854, 480, 9), (1600, 900, 3)):
            found = analyze(fake_hotbar(w, h, sel), w)
            self.assertIsNotNone(found, (w, h))
            self.assertEqual(found["slot"], sel, (w, h))
            self.assertEqual(found["scale"], auto_gui_scale(w, h))

    def test_fixed_gui_scale(self):
        found = analyze(fake_hotbar(1920, 1080, 7, scale=2), 1920)
        self.assertEqual((found["scale"], found["slot"]), (2, 7))

    def test_nothing_found_without_hotbar(self):
        shot = Shot(800, 100, bytes((10, 200, 30, 255)) * 80000, 600)
        self.assertIsNone(analyze(shot, 800))

    def test_item_icon(self):
        shot = fake_hotbar(1280, 720, 4, item_slot=4)
        found = analyze(shot, 1280)
        rows = item_pixels(shot, found, 4)
        self.assertEqual(rows[0][0], (240, 200, 60))
        self.assertEqual(rows[0][1], (200, 40, 40))
        self.assertFalse(looks_empty(rows))
        self.assertTrue(looks_empty(item_pixels(shot, found, 2)))
        url = png_data_url(rows)
        png = base64.b64decode(url.split(",", 1)[1])
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (16, 16))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), 16 * (1 + 16 * 3))
        self.assertLess(len(url), 4000)


class SlotTrackerTests(unittest.TestCase):
    def test_keys_and_wheel(self):
        t = SlotTracker()
        self.assertTrue(t.key("3"))
        self.assertEqual(t.slot, 3)
        t.wheel(up=False)
        self.assertEqual(t.slot, 4)
        t.key("1")
        t.wheel(up=True)
        self.assertEqual(t.slot, 9)  # links herum
        self.assertFalse(t.key("0"))

    def test_chat_and_inventory_ignored(self):
        t = SlotTracker()
        t.key("t")
        t.key("5")             # im Chat getippt
        self.assertEqual(t.slot, 1)
        t.key("enter")
        t.key("e")             # Inventar
        t.key("2")
        t.wheel(up=False)
        self.assertEqual(t.slot, 1)
        t.key("esc")
        t.key("2")
        self.assertEqual(t.slot, 2)
        t.key("t")
        t.sync(6)              # Hotbar sichtbar erkannt -> nichts mehr offen
        t.key("7")
        self.assertEqual(t.slot, 7)


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


class LearnTests(unittest.TestCase):
    def test_learn_and_delete_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app._apply(initial=True)
            app.engine.start_threads()
            try:
                app.engine.start()
                st = app.tools_action({"op": "learn"})
                self.assertTrue(st["learning"])
                self.assertFalse(st["engine"]["armed"])  # Anlernen schaltet den Klicker aus
                app._on_raw_input("k", "3", True)        # Spitzhacke auf Platz 3
                app._on_mouse("left", True)
                time.sleep(0.45)                          # Block abbauen
                app._on_mouse("left", False)
                for _ in range(50):
                    if not app.learning:
                        break
                    time.sleep(0.05)
                self.assertFalse(app.learning)
                self.assertEqual(app.config.tools(), [{"slot": 3, "icon": ""}])
                self.assertEqual(app.notice["key"], "n_tool_saved")

                # Im PvP-Modus: Platz 3 = Werkzeug, Platz 1 = Schwert
                app.handle("preset", {"id": "pvp"})
                app._on_raw_input("k", "3", True)
                self.assertTrue(app.engine.tool)
                app._on_raw_input("w", "up", True)
                self.assertEqual(app.slots.slot, 2)
                self.assertFalse(app.engine.tool)

                st = app.tools_action({"op": "delete", "slot": 3})
                self.assertEqual(st["config"]["tools"], [])
                self.assertEqual(app.tools_action({"op": "delete", "slot": 3}), {"error": "e_not_found"})
            finally:
                app.engine.shutdown()

    def test_short_click_does_not_learn(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, "web", demo=True, keep_alive=True)
            app.tools_action({"op": "learn"})
            app._on_mouse("left", True)
            app._on_mouse("left", False)  # nur geklickt, nichts abgebaut
            time.sleep(0.1)
            self.assertTrue(app.learning)
            app.tools_action({"op": "cancel"})
            self.assertFalse(app.learning)
            self.assertEqual(app.config.tools(), [])


if __name__ == "__main__":
    unittest.main()
