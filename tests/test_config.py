import json
import os
import tempfile
import unittest

from clicker.config import PRESET_ORDER, Config


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
        self.assertEqual(c.data["hotkey"], "f6")
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
        self.assertFalse(c.select("quatsch"))

    def test_variation_and_limits(self):
        c = Config(self.dir)
        c.load()
        c.update({"preset": {"cps": 10}, "general": {"vary": True, "auto_stop": 30, "start_delay": "2,5"}})
        s = c.click_settings()
        self.assertAlmostEqual(s.cps_min, 8.8)
        self.assertAlmostEqual(s.cps_max, 11.2)
        self.assertEqual(s.limit_seconds, 30)
        self.assertEqual(s.start_delay, 2.5)

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
        self.assertEqual(c.data["hotkey"], "home")
        self.assertEqual(c.migrated_from, "autoclicker_settings.json")

    def test_migrates_tk_key_names(self):
        with open(os.path.join(self.dir, "ac_settings.json"), "w") as f:
            json.dump({"interval_ms": "100", "hotkey_start": "Prior", "auto_stop_sec": "20"}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["hotkey"], "pageup")
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
