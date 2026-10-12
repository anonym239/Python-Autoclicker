"""Echter Windows-Test: Klicks per SendInput, globale Hooks, Hotkeys.

Laeuft nur unter Windows (bzw. Wine) und wird sonst uebersprungen.
Achtung: sendet echte Maus- und Tastatureingaben (F24 + Klicks).
"""

import ctypes
import os
import sys
import time
import unittest

if sys.platform == "win32":
    from clicker import platform_win as pw
    from clicker.keys import HotkeyMatcher


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@unittest.skipUnless(sys.platform == "win32", "nur unter Windows")
@unittest.skipIf(os.environ.get("CI"), "braucht einen echten Desktop (nicht in CI)")
class WindowsBackendTests(unittest.TestCase):
    def setUp(self):
        self.be = pw.WindowsBackend()
        self.hotkeys = []
        self.mouse = []
        self.records = []
        self.matcher = HotkeyMatcher(lambda s, d: self.hotkeys.append((s, d)),
                                     lambda b, d: self.mouse.append((b, d)),
                                     lambda s, t: self.records.append((s, t)))
        self.matcher.set_bindings({"toggle": "f24", "stop": "ctrl+f23"})
        self.be.set_mouse_hook(True)
        self.be.start_input(self.matcher)

    def tearDown(self):
        self.be.stop_input()

    def send_key(self, vk, down):
        arr = (pw.INPUT * 1)()
        arr[0].type = 1  # INPUT_KEYBOARD
        arr[0].u.ki = pw.KEYBDINPUT(vk, 0, 0 if down else 0x0002, 0, 0)
        return pw.user32.SendInput(1, arr, ctypes.sizeof(pw.INPUT))

    def send_foreign_click(self):
        arr = (pw.INPUT * 2)()
        for i, flag in enumerate((0x0002, 0x0004)):
            arr[i].type = 0
            arr[i].u.mi = pw.MOUSEINPUT(0, 0, 0, flag, 0, 0)  # ohne MAGIC = "fremder" Klick
        return pw.user32.SendInput(2, arr, ctypes.sizeof(pw.INPUT))

    def test_struct_sizes(self):
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(pw.INPUT), expected)

    def test_hooks_installed(self):
        self.assertTrue(self.be.hooks_ok)

    def test_hotkey_from_keyboard_hook(self):
        self.send_key(0x87, True)   # F24
        self.send_key(0x87, False)
        self.assertTrue(wait_for(lambda: len(self.hotkeys) >= 2), self.hotkeys)
        self.assertEqual(self.hotkeys[:2], [("toggle", True), ("toggle", False)])

    def test_modifier_combo(self):
        self.send_key(0xA2, True)   # linke Strg
        self.send_key(0x86, True)   # F23
        self.send_key(0x86, False)
        self.send_key(0xA2, False)
        self.assertTrue(wait_for(lambda: ("stop", True) in self.hotkeys), self.hotkeys)

    def test_own_clicks_are_ignored_foreign_clicks_seen(self):
        self.assertEqual(self.be._both["left"]._length_, 2)
        self.be.click("left")
        self.be.click("right")
        time.sleep(0.3)
        self.assertEqual(self.mouse, [], "eigene Klicks duerfen nicht als 'gehalten' zaehlen")
        self.send_foreign_click()
        self.assertTrue(wait_for(lambda: len(self.mouse) >= 2), self.mouse)
        self.assertEqual(self.mouse[:2], [("left", True), ("left", False)])

    def test_mouse_hook_can_be_removed(self):
        self.be.set_mouse_hook(False)
        time.sleep(0.2)
        self.send_foreign_click()
        time.sleep(0.3)
        self.assertEqual(self.mouse, [])

    def test_recording_through_hook(self):
        self.matcher.start_recording("stop")
        self.send_key(0x52, True)   # R
        self.send_key(0x52, False)
        self.assertTrue(wait_for(lambda: self.records), self.records)
        self.assertEqual(self.records[0], ("stop", "r"))

    def test_window_helpers(self):
        self.assertIsInstance(self.be.foreground_title(), str)
        self.be.set_timer_resolution(True)
        self.be.set_timer_resolution(False)
        self.assertFalse(self.be.set_topmost("gibt-es-sicher-nicht-123", True))

    def test_click_rate_with_engine(self):
        from clicker.engine import ClickEngine, ClickSettings, SmartSettings
        counted = []
        orig = self.be.click

        def counting(button):
            counted.append(time.perf_counter())
            orig(button)

        self.be.click = counting
        e = ClickEngine(self.be)
        e.configure(ClickSettings(cps_min=100, cps_max=100, limit_seconds=1.0), SmartSettings())
        e.start_threads()
        try:
            e.start()
            self.assertTrue(wait_for(lambda: not e.armed, 4))
        finally:
            e.shutdown()
        self.assertTrue(95 <= len(counted) <= 102, len(counted))
        self.assertEqual(self.mouse, [])


if __name__ == "__main__":
    unittest.main()
