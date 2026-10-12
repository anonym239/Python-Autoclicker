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

    def test_starts_immediately_without_countdown(self):
        self.configure(cps_min=50, cps_max=50)
        self.e.start()
        self.assertTrue(self.e.armed)
        self.assertTrue(wait_for(lambda: self.be.clicks > 0, 0.2), "erster Klick muss sofort kommen")
        self.assertEqual(self.events, ["start"])

    def test_rate_is_accurate(self):
        self.configure(cps_min=50, cps_max=50)
        self.e.start()
        self.assertTrue(wait_for(lambda: self.be.clicks > 0))
        n = self.run_for(1.0)
        self.assertTrue(44 <= n <= 56, n)

    def test_random_range(self):
        self.configure(cps_min=20, cps_max=40)
        self.e.start()
        n = self.run_for(1.0)
        self.assertTrue(17 <= n <= 43, n)

    def test_toggle_and_stop(self):
        self.configure(cps_min=50, cps_max=50)
        self.e.toggle()
        self.assertTrue(self.e.armed)
        self.e.toggle()
        self.assertFalse(self.e.armed)
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.15), 0)
        self.assertEqual(self.events, ["start", "stop"])

    def test_auto_stop(self):
        self.configure(cps_min=20, cps_max=20, limit_seconds=0.3)
        self.e.start()
        self.assertTrue(wait_for(lambda: not self.e.armed, 1.5))
        self.assertTrue(4 <= self.be.clicks <= 9, self.be.clicks)
        self.assertEqual(self.e.status()["stop_reason"], "limit")
        self.assertIn("limit", self.events)

    def test_hold_mouse_mode(self):
        self.configure(mode="hold_mouse", cps_min=40, cps_max=40)
        self.e.start()
        self.assertTrue(wait_for(lambda: self.e.status()["state"] == "ready"))
        self.assertEqual(self.run_for(0.2), 0)
        self.e.set_mouse_held("right", True)  # falsche Taste
        self.assertEqual(self.run_for(0.15), 0)
        self.e.set_mouse_held("left", True)
        self.assertGreater(self.run_for(0.3), 6)
        self.e.set_mouse_held("left", False)
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.2), 0)

    def click_like_a_human(self, times, hold=0.02, gap=0.08):
        for _ in range(times):
            self.e.set_mouse_held("left", True)
            time.sleep(hold)
            self.e.set_mouse_held("left", False)
            time.sleep(gap)

    def test_boost_doubles_real_clicks(self):
        self.configure(mode="boost", boost=2)
        self.e.start()
        self.assertTrue(wait_for(lambda: self.e.status()["state"] == "ready"))
        self.click_like_a_human(5)
        self.assertTrue(wait_for(lambda: self.be.clicks == 5, 1.0), self.be.clicks)
        time.sleep(0.1)
        self.assertEqual(self.be.clicks, 5)                       # 5 Extra-Klicks
        self.assertEqual(self.e.status()["session_clicks"], 10)  # echt + extra

    def test_boost_x3(self):
        self.configure(mode="boost", boost=3)
        self.e.start()
        self.click_like_a_human(4)
        self.assertTrue(wait_for(lambda: self.be.clicks == 8, 1.0), self.be.clicks)

    def test_boost_never_lost_when_clicking_very_fast(self):
        # Zu schnell fuer die Extra-Klicks: nichts geht verloren, sie kommen nach dem Loslassen
        self.configure(mode="boost", boost=2)
        self.e.start()
        self.click_like_a_human(5, hold=0.005, gap=0.003)
        self.assertTrue(wait_for(lambda: self.be.clicks == 5, 1.5), self.be.clicks)
        time.sleep(0.15)
        self.assertEqual(self.be.clicks, 5)

    def test_boost_never_clicks_while_button_is_held(self):
        self.configure(mode="boost", boost=3)
        self.e.start()
        self.e.set_mouse_held("left", True)
        self.e.set_mouse_held("left", False)
        self.e.set_mouse_held("left", True)  # sofort wieder gedrueckt und gehalten
        self.assertEqual(self.run_for(0.2), 0)
        self.e.set_mouse_held("left", False)
        self.assertTrue(wait_for(lambda: self.be.clicks == 4, 1.0), self.be.clicks)

    def test_boost_ignores_clicks_when_off(self):
        self.configure(mode="boost", boost=2)
        self.click_like_a_human(2)
        time.sleep(0.1)
        self.assertEqual(self.be.clicks, 0)
        self.assertEqual(self.e.status()["session_clicks"], 0)

    def test_window_lock_and_self_protection(self):
        smart = SmartSettings(window_lock=True, window_match=["Minecraft", "Lunar Client"])
        self.configure(smart=smart, cps_min=50, cps_max=50)
        self.be.foreground = "Discord"
        self.e.start()
        self.assertTrue(wait_for(lambda: self.e.status()["reason"] == "window"))
        self.assertEqual(self.run_for(0.2), 0)
        self.be.foreground = "Lunar Client 1.8.9"
        self.assertGreater(self.run_for(0.3), 5)
        self.configure(cps_min=50, cps_max=50)  # Sperre aus
        self.be.foreground = "AutoClicker 6"
        self.assertTrue(wait_for(lambda: self.e.status()["reason"] == "self"))
        time.sleep(0.05)
        self.assertEqual(self.run_for(0.2), 0)

    def test_stats_and_reset_keep_lifetime(self):
        self.configure(cps_min=100, cps_max=100, limit_seconds=0.3)
        self.e.lifetime_base = 1000
        self.e.start()
        self.assertTrue(wait_for(lambda: not self.e.armed))
        self.assertTrue(wait_for(lambda: self.e.status()["best_cps"] > 0, 1.0))
        clicks = self.e.status()["session_clicks"]
        self.assertEqual(self.e.lifetime_clicks(), 1000 + clicks)
        self.e.reset_stats()
        st = self.e.status()
        self.assertEqual(st["session_clicks"], 0)
        self.assertEqual(st["lifetime_clicks"], 1000 + clicks)
        self.assertEqual(st["best_cps"], 0)


if __name__ == "__main__":
    unittest.main()
