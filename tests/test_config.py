import json
import os
import tempfile
import unittest

from clicker.config import MAX_PROFILES, Config, sanitize_profile


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_defaults_and_roundtrip(self):
        c = Config(self.dir)
        c.load()
        names = [p["name"] for p in c.data["profiles"]]
        self.assertIn("PvP 1.8", names)
        self.assertIn("AFK Angeln", names)
        self.assertEqual(c.data["hotkeys"]["toggle"], "f6")
        token = c.data["app"]["token"]
        self.assertGreaterEqual(len(token), 8)
        c.update({"profile": {"cps_min": 7, "cps_max": 9}, "smart": {"window_lock": True}})
        self.assertTrue(c.save())
        c2 = Config(self.dir)
        c2.load()
        self.assertEqual(c2.data["app"]["token"], token)
        self.assertEqual(c2.active_profile()["cps_max"], 9)
        self.assertTrue(c2.smart_settings().window_lock)

    def test_migrates_v5_settings(self):
        with open(os.path.join(self.dir, "autoclicker_settings.json"), "w") as f:
            json.dump({"interval_ms": "1", "hotkey_start": "home", "hotkey_stop": "up",
                       "mouse_start_clicks": 3}, f)
        c = Config(self.dir)
        c.load()
        p = c.active_profile()
        self.assertEqual(p["name"], "Mein v5")
        self.assertEqual(p["cps_min"], 1000)
        self.assertEqual(c.data["hotkeys"]["toggle"], "home")
        self.assertEqual(c.data["hotkeys"]["stop"], "up")
        self.assertEqual(c.migrated_from, "autoclicker_settings.json")

    def test_migrates_tk_key_names(self):
        with open(os.path.join(self.dir, "ac_settings.json"), "w") as f:
            json.dump({"interval_ms": "100", "hotkey_start": "Prior", "hotkey_stop": "Prior"}, f)
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["hotkeys"]["toggle"], "pageup")
        self.assertEqual(c.data["hotkeys"]["stop"], "")
        self.assertEqual(c.active_profile()["cps_min"], 10)

    def test_corrupt_file_falls_back(self):
        with open(os.path.join(self.dir, "clicker_settings.json"), "w") as f:
            f.write("{kaputt")
        c = Config(self.dir)
        c.load()
        self.assertEqual(c.data["version"], 6)

    def test_sanitize(self):
        p = sanitize_profile({"cps_min": 5000, "mode": "quatsch", "button": "right",
                              "limit_clicks": "12,7", "start_delay": -3})
        self.assertEqual(p["cps_min"], 1000)
        self.assertEqual(p["cps_max"], 1000)
        self.assertEqual(p["mode"], "toggle")
        self.assertEqual(p["button"], "right")
        self.assertEqual(p["limit_clicks"], 13)
        self.assertEqual(p["start_delay"], 0)
        base = sanitize_profile({"cps_min": 10, "cps_max": 14})
        lowered = sanitize_profile({"cps_max": 6}, base)
        self.assertEqual((lowered["cps_min"], lowered["cps_max"]), (6, 6))

    def test_profile_ops(self):
        c = Config(self.dir)
        c.load()
        self.assertIsNone(c.profile_op("select", "Bridging"))
        self.assertEqual(c.active_profile()["button"], "right")
        self.assertIsNone(c.profile_op("duplicate"))
        self.assertEqual(c.data["active"], "Bridging 2")
        self.assertIsNone(c.profile_op("rename", "", "Godbridge"))
        self.assertEqual(c.data["active"], "Godbridge")
        self.assertEqual(c.profile_op("rename", "", "PvP 1.8"), None)
        self.assertEqual(c.data["active"], "PvP 1.8 2")  # Name schon vergeben
        self.assertIsNone(c.profile_op("delete"))
        self.assertNotIn("PvP 1.8 2", [p["name"] for p in c.data["profiles"]])
        names = [p["name"] for p in c.data["profiles"]]
        c.data["active"] = names[-1]
        c.profile_op("next")
        self.assertEqual(c.data["active"], names[0])
        while len(c.data["profiles"]) < MAX_PROFILES:
            self.assertIsNone(c.profile_op("create", new_name="X"))
        self.assertIsNotNone(c.profile_op("create"))
        while len(c.data["profiles"]) > 1:
            self.assertIsNone(c.profile_op("delete"))
        self.assertIsNotNone(c.profile_op("delete"))

    def test_update_ignores_token_and_rename(self):
        c = Config(self.dir)
        c.load()
        tok = c.data["app"]["token"]
        c.update({"app": {"token": "hackhackhack", "theme": "diamond"}, "profile": {"name": "X"}})
        self.assertEqual(c.data["app"]["token"], tok)
        self.assertEqual(c.data["app"]["theme"], "diamond")
        self.assertEqual(c.data["active"], "Standard")


if __name__ == "__main__":
    unittest.main()
