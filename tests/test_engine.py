import time
import unittest

from clicker.backend import DemoBackend
from clicker.engine import ClickEngine, ClickSettings, SmartSettings


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.be = DemoBackend()
        self.events = []
        self.e = ClickEngine(self.be)
        self.e.on_event = self.events.append
        self.e.start_threads()

    def tearDown(self):
        self.e.shutdown()

    def configure(self, smart=None, **kw):
        self.e.configure(ClickSettings(**kw), smart or SmartSettings())

    def run_for(self, seconds):
        start = self.be.clicks
        time.sleep(seconds)
        return self.be.clicks - start

    def test_rate_is_accurate(self):
        self.configure(cps_min=50, cps_max=50)
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: self.be.clicks > 0))
        n = self.run_for(1.0)
        self.assertTrue(44 <= n <= 56, n)
        self.assertEqual(self.events, ["start"])

    def test_random_range(self):
        self.configure(cps_min=20, cps_max=40)
        self.e.start("hotkey")
        n = self.run_for(1.0)
        self.assertTrue(17 <= n <= 43, n)

    def test_limit_clicks_exact(self):
        self.configure(cps_min=200, cps_max=200, limit_clicks=25)
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: not self.e.armed))
        time.sleep(0.05)
        self.assertEqual(self.be.clicks, 25)
        st = self.e.status()
        self.assertEqual(st["stop_reason"], "limit")
        self.assertIn("limit", self.events)

    def test_limit_seconds(self):
        self.configure(cps_min=20, cps_max=20, limit_seconds=0.3)
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: not self.e.armed, 1.5))
        self.assertTrue(4 <= self.be.clicks <= 9, self.be.clicks)

    def test_countdown_and_ui_minimum(self):
        self.configure(start_delay=0.3)
        self.e.start("hotkey")
        self.assertEqual(self.e.status()["state"] if wait_for(
            lambda: self.e.status()["state"] == "countdown", 0.2) else None, "countdown")
        self.assertEqual(self.be.clicks, 0)
        self.assertTrue(wait_for(lambda: self.be.clicks > 0, 1.0))
        self.e.stop()
        self.e.start("ui")
        cd = self.e.status()["countdown"]
        self.assertTrue(2.8 <= cd <= 3.0, cd)
        self.e.toggle("ui")  # Abbruch waehrend Countdown
        self.assertIsNone(self.e.status()["countdown"])

    def test_hold_mouse_mode(self):
        self.configure(mode="hold_mouse", cps_min=40, cps_max=40)
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: self.e.status()["state"] == "ready"))
        self.assertEqual(self.run_for(0.2), 0)
        self.e.set_mouse_held("right", True)  # falsche Taste
        self.assertEqual(self.run_for(0.15), 0)
        self.e.set_mouse_held("left", True)
        self.assertGreater(self.run_for(0.3), 6)
        self.e.set_mouse_held("left", False)
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.2), 0)

    def test_hold_key_mode(self):
        self.configure(mode="hold_key", cps_min=40, cps_max=40)
        self.e.start("ui")  # in diesem Modus ohne Wirkung
        self.assertIsNone(self.e.status()["countdown"])
        self.assertEqual(self.run_for(0.15), 0)
        self.e.set_key_held(True)
        self.assertGreater(self.run_for(0.3), 6)
        self.e.set_key_held(False)
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.2), 0)

    def test_window_lock_and_self_protection(self):
        smart = SmartSettings(window_lock=True, window_match=["Minecraft", "Lunar Client"])
        self.configure(smart=smart, cps_min=50, cps_max=50)
        self.be.foreground = "Discord"
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: self.e.status()["reason"] == "window"))
        self.assertEqual(self.run_for(0.2), 0)
        self.be.foreground = "Lunar Client 1.8.9"
        self.assertGreater(self.run_for(0.3), 5)
        self.configure(cps_min=50, cps_max=50)  # Sperre aus
        self.be.foreground = "AutoClicker 6"
        self.assertTrue(wait_for(lambda: self.e.status()["reason"] == "self"))
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.2), 0)

    def test_pause_in_menus(self):
        self.configure(smart=SmartSettings(pause_in_menus=True), cps_min=50, cps_max=50)
        self.be.captured = False
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: self.e.status()["reason"] == "menu"))
        self.assertEqual(self.run_for(0.2), 0)
        self.be.captured = True
        self.assertGreater(self.run_for(0.3), 5)

    def test_hold_action_presses_and_releases(self):
        self.configure(action="hold", button="right")
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: "right" in self.be.down))
        self.assertTrue(self.e.status()["holding"])
        self.e.stop()
        self.assertTrue(wait_for(lambda: "right" not in self.be.down))
        self.assertEqual(self.be.clicks, 0)

    def test_hold_released_when_window_changes(self):
        smart = SmartSettings(window_lock=True, window_match=["Minecraft"])
        self.configure(smart=smart, action="hold")
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: "left" in self.be.down))
        self.be.foreground = "Explorer"
        self.assertTrue(wait_for(lambda: "left" not in self.be.down))

    def test_boost_doubles_real_clicks(self):
        self.configure(mode="boost", boost=2)
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: self.e.status()["state"] == "ready"))
        for _ in range(5):  # 5 echte Klicks
            self.e.set_mouse_held("left", True)
            time.sleep(0.02)
            self.e.set_mouse_held("left", False)
            time.sleep(0.08)
        time.sleep(0.1)
        self.assertEqual(self.be.clicks, 5)            # 5 Extra-Klicks
        self.assertEqual(self.e.status()["session_clicks"], 10)  # echt + extra

    def test_boost_x3_and_fast_reclick(self):
        self.configure(mode="boost", boost=3)
        self.e.start("hotkey")
        self.e.set_mouse_held("left", True)
        self.e.set_mouse_held("left", False)
        time.sleep(0.15)
        self.assertEqual(self.be.clicks, 2)
        # Sofort wieder gedrueckt -> ausstehende Extra-Klicks verfallen
        self.e.set_mouse_held("left", True)
        self.e.set_mouse_held("left", False)
        self.e.set_mouse_held("left", True)
        time.sleep(0.15)
        self.assertEqual(self.be.clicks, 2)
        self.e.set_mouse_held("left", False)

    def test_boost_ignores_clicks_when_off(self):
        self.configure(mode="boost", boost=2)
        self.e.set_mouse_held("left", True)
        self.e.set_mouse_held("left", False)
        time.sleep(0.12)
        self.assertEqual(self.be.clicks, 0)
        self.assertEqual(self.e.status()["session_clicks"], 0)

    def test_stats_and_reset_keep_lifetime(self):
        self.configure(cps_min=100, cps_max=100, limit_clicks=30)
        self.e.lifetime_base = 1000
        self.e.start("hotkey")
        self.assertTrue(wait_for(lambda: not self.e.armed))
        self.assertTrue(wait_for(lambda: self.e.status()["best_cps"] > 0, 1.0))
        self.assertEqual(self.e.lifetime_clicks(), 1030)
        self.e.reset_stats()
        st = self.e.status()
        self.assertEqual(st["session_clicks"], 0)
        self.assertEqual(st["lifetime_clicks"], 1030)
        self.assertEqual(st["best_cps"], 0)


if __name__ == "__main__":
    unittest.main()
