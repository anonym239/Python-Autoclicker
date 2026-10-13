import json
import os
import tempfile
import unittest

import re

from clicker.config import LANGUAGES, PRESET_ORDER, Config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_defaults_and_roundtrip(self):
        c = Config(self.dir)
        c.load()
        self.assertEqual(list(c.data["presets"]), list(PRESET_ORDER))
        self.assertEqual(c.hotkeys(), [{"key": "f6", "action": "toggle"}])
        self.assertEqual(c.mode(), "toggle")
        token = c.data["general"]["token"]
        self.assertGreaterEqual(len(token), 8)
        c.update({"preset": {"cps": 7}, "general": {"window_lock": True, "theme": "dark"}})
        self.assertTrue(c.save())
        c2 = Config(self.dir)
        c2.load()
        self.assertEqual(c2.data["general"]["token"], token)
        self.assertEqual(c2.current()["cps"], 7)
        self.assertTrue(c2.smart_settings().window_lock)
        self.assertEqual(c2.data["general"]["theme"], "dark")

    def test_presets(self):
        c = Config(self.dir)
        c.load()
        self.assertTrue(c.select("pvp"))
        s = c.click_settings()
        self.assertEqual((s.mode, s.button, s.cps_min, s.cps_max), ("hold_mouse", "left", 13, 13))
        self.assertTrue(c.select("boost"))
        self.assertEqual(c.click_settings().mode, "boost")
        self.assertEqual(c.click_settings().boost, 2)
        c.update({"preset": {"boost": 9}})
        self.assertEqual(c.current()["boost"], 3)
        self.assertTrue(c.select("afk"))
        self.assertEqual(c.click_settings().cps_max, 1.6)
        self.assertEqual(c.click_settings().action, "click")
        c.update({"preset": {"action": "hold"}})
        self.assertEqual(c.click_settings().action, "hold")
        c.update({"preset": {"action": "explode"}})
        self.assertEqual(c.click_settings().action, "hold")
        self.assertFalse(c.select("quatsch"))

    def test_variation_and_limits(self):
        c = Config(self.dir)
        c.load()
        c.update({"preset": {"cps": 10}, "general": {"vary": True, "auto_stop": "30,5"}})
        s = c.click_settings()
        self.assertAlmostEqual(s.cps_min, 8.8)
        self.assertAlmostEqual(s.cps_max, 11.2)
        self.assertEqual(s.limit_seconds, 30.5)
        self.assertEqual(s.start_delay, 0)  # Standard: sofort klicken
        c.update({"general": {"start_delay": 99}})
        self.assertEqual(c.click_settings().start_delay, 60)

    def test_hotkeys(self):
        c = Config(self.dir)
        c.load()
        self.assertIsNone(c.set_hotkey(None, "mouse4"))
        self.assertIsNone(c.set_hotkey(None, "Ctrl+R"))
        self.assertEqual(c.set_hotkey(None, "f6"), "e_key_taken")
        self.assertEqual(c.set_hotkey(None, "quatsch"), "e_key_invalid")
        self.assertTrue(c.set_hotkey_action(1, "on"))
        self.assertFalse(c.set_hotkey_action(1, "explode"))
        self.assertIsNone(c.set_hotkey(0, "f8"))  # vorhandenen Hotkey aendern
        self.assertEqual(c.hotkeys(), [{"key": "f8", "action": "toggle"},
                                       {"key": "mouse4", "action": "on"},
                                       {"key": "ctrl+r", "action": "toggle"}])
        self.assertTrue(c.delete_hotkey(2))
        self.assertFalse(c.delete_hotkey(7))
        c.save()
        c2 = Config(self.dir)
        c2.load()
        self.assertEqual(len(c2.hotkeys()), 2)

    def test_old_single_hotkey_is_converted(self):
        with open(os.path.join(self.dir, "clicker_settings.json"), "w") as f:
            json.dump({"general": {}, "hotkey": "f7", "hotkeys": None}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.hotkeys(), [{"key": "f7", "action": "toggle"}])

    def test_language(self):
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["general"]["language"], "auto")
        c.update({"general": {"language": "fr"}})
        self.assertEqual(c.data["general"]["language"], "fr")
        c.update({"general": {"language": "klingonisch"}})
        self.assertEqual(c.data["general"]["language"], "fr")

    def test_languages_match_ui(self):
        with open(os.path.join(ROOT, "web", "i18n.js"), encoding="utf-8") as f:
            js = f.read()
        ui = re.findall(r'\["(\w\w)", "', js.split("window.AC_I18N")[0])
        self.assertEqual(["auto"] + ui, list(LANGUAGES))

    def test_old_tool_masks_are_dropped(self):
        rim = f"{(1 << 16) - 1:064x}"            # oberste Zeile gesetzt = alter Eintrag bis 6.9
        good = f"{0b111 << (5 * 16 + 5):064x}"   # nur Pixel innen
        with open(os.path.join(self.dir, "clicker_settings.json"), "w", encoding="utf-8") as f:
            json.dump({"general": {}, "tools": [{"mask": rim, "icon": ""}, {"mask": good, "icon": ""},
                                                {"slot": 3, "icon": ""}]}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.tools(), [{"mask": good, "icon": ""}])

    def test_sanitize(self):
        c = Config(self.dir)
        c.load()
        c.update({"preset": {"cps": 5000, "button": "quatsch"}, "general": {"theme": "pink", "auto_stop": -5}})
        self.assertEqual(c.current()["cps"], 1000)
        self.assertEqual(c.current()["button"], "left")
        self.assertEqual(c.data["general"]["theme"], "system")
        self.assertEqual(c.data["general"]["auto_stop"], 0)
        tok = c.data["general"]["token"]
        c.update({"general": {"token": "hackhackhack", "port": 1}})
        self.assertEqual(c.data["general"]["token"], tok)
        self.assertEqual(c.data["general"]["port"], 8765)

    def test_migrates_v5_settings(self):
        with open(os.path.join(self.dir, "autoclicker_settings.json"), "w") as f:
            json.dump({"interval_ms": "1", "hotkey_start": "home", "hotkey_stop": "up",
                       "mouse_start_clicks": 3}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["presets"]["standard"]["cps"], 1000)
        # v5 hatte getrennte Start- und Stopp-Tasten
        self.assertEqual(c.hotkeys(), [{"key": "home", "action": "on"}, {"key": "up", "action": "off"}])
        self.assertEqual(c.migrated_from, "autoclicker_settings.json")

    def test_migrates_tk_key_names(self):
        with open(os.path.join(self.dir, "ac_settings.json"), "w") as f:
            json.dump({"interval_ms": "100", "hotkey_start": "Prior", "auto_stop_sec": "20"}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.hotkeys(), [{"key": "pageup", "action": "toggle"}])
        self.assertEqual(c.data["presets"]["standard"]["cps"], 10)
        self.assertEqual(c.data["general"]["auto_stop"], 20)

    def test_corrupt_file_falls_back(self):
        with open(os.path.join(self.dir, "clicker_settings.json"), "w") as f:
            f.write("{kaputt")
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["version"], 6)
        self.assertEqual(c.data["preset"], "standard")


if __name__ == "__main__":
    unittest.main()


class KitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Config(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kits(self):
        c = self.c
        mask = f"{0b111 << (5 * 16 + 5):064x}"
        c.learn_tool(mask, "")
        self.assertEqual(c.kits(), [{"name": "Kit 1", "count": 1}])
        self.assertIsNone(c.new_kit("  Sky   Wars  "))
        self.assertEqual(c.kit_index(), 1)
        self.assertEqual(c.tools(), [])                     # neues Kit ist leer
        self.assertTrue(c.select_kit(0))
        self.assertEqual(len(c.tools()), 1)
        self.assertTrue(c.rename_kit(0, "BedWars"))
        self.assertEqual([k["name"] for k in c.kits()], ["BedWars", "Sky Wars"])
        self.assertFalse(c.select_kit(5))
        c.save()
        again = Config(self.tmp.name)
        again.load()
        self.assertEqual(again.kits(), c.kits())
        self.assertEqual(again.kit_index(), 0)
        # loeschen: das gewaehlte bleibt gewaehlt, das letzte Kit bleibt immer da
        c.select_kit(1)
        self.assertTrue(c.delete_kit(0))
        self.assertEqual((c.kit_index(), c.active_kit_name()), (0, "Sky Wars"))
        self.assertTrue(c.delete_kit(0))
        self.assertEqual(c.kits(), [{"name": "Kit 1", "count": 0}])
        for _ in range(20):
            c.new_kit()
        self.assertEqual(len(c.kits()), 10)
        self.assertEqual(c.new_kit(), "e_max_kits")

    def test_old_tools_become_kit(self):
        mask = f"{0b111 << (5 * 16 + 5):064x}"
        with open(os.path.join(self.tmp.name, "clicker_settings.json"), "w", encoding="utf-8") as f:
            json.dump({"general": {}, "tools": [{"mask": mask, "icon": ""}]}, f)
        c = Config(self.tmp.name)
        c.load()
        self.assertEqual(c.kits(), [{"name": "Kit 1", "count": 1}])
