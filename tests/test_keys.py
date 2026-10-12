import unittest

from clicker.keys import HotkeyMatcher, normalize_hotkey, parse_hotkey, vk_to_name


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class ParseTests(unittest.TestCase):
    def test_parse_and_format(self):
        hk = parse_hotkey("Ctrl + Shift + F6")
        self.assertEqual(hk.mods, frozenset({"ctrl", "shift"}))
        self.assertEqual(hk.key, "f6")
        self.assertEqual(str(hk), "ctrl+shift+f6")
        self.assertEqual(normalize_hotkey("shift+ctrl+r"), "ctrl+shift+r")

    def test_invalid(self):
        for text in ("", "ctrl+", "foo", "ctrl+foo", "hyper+a", None):
            self.assertIsNone(parse_hotkey(text), text)
        self.assertEqual(normalize_hotkey("quatsch"), "")

    def test_special_names(self):
        self.assertEqual(normalize_hotkey("mouse4"), "mouse4")
        self.assertEqual(normalize_hotkey("shift"), "shift")
        self.assertEqual(vk_to_name(0x75), "f6")
        self.assertEqual(vk_to_name(0x41), "a")
        self.assertEqual(vk_to_name(0xA2), "ctrl")
        self.assertEqual(vk_to_name(0xFF), "vkff")
        self.assertEqual(normalize_hotkey("vkff"), "vkff")


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fired = []
        self.mouse = []
        self.records = []
        self.m = HotkeyMatcher(lambda s, d: self.fired.append((s, d)),
                               lambda b, d: self.mouse.append((b, d)),
                               lambda s, t: self.records.append((s, t)),
                               clock=self.clock)
        self.m.set_bindings({"toggle": "f6", "stop": "ctrl+f6", "next_profile": "mouse4"})

    def test_simple_press_and_repeat(self):
        self.m.key_event("f6", True)
        self.m.key_event("f6", True)   # Auto-Repeat
        self.clock.t += 0.03
        self.m.key_event("f6", True)
        self.m.key_event("f6", False)
        self.assertEqual(self.fired, [("toggle", True), ("toggle", False)])

    def test_most_specific_binding_wins(self):
        self.m.key_event("ctrl", True)
        self.m.key_event("f6", True)
        self.assertEqual(self.fired, [("stop", True)])

    def test_plain_hotkey_works_while_sprinting(self):
        self.m.set_bindings({"toggle": "f6"})
        self.m.key_event("ctrl", True)  # Sprinten
        self.m.key_event("f6", True)
        self.assertEqual(self.fired, [("toggle", True)])

    def test_missed_key_up_recovers(self):
        self.m.key_event("f6", True)
        self.clock.t += 5  # Loslassen wurde verpasst (z. B. Sperrbildschirm)
        self.m.key_event("f6", True)
        self.assertEqual(self.fired, [("toggle", True), ("toggle", True)])

    def test_mouse_buttons(self):
        self.m.mouse_event("x1", True)
        self.m.mouse_event("x1", False)
        self.m.mouse_event("left", True)
        self.assertEqual(self.fired, [("next_profile", True), ("next_profile", False)])
        self.assertEqual(self.mouse, [("left", True)])
        self.assertTrue(self.m.wants_mouse_buttons())

    def test_recording(self):
        self.m.start_recording("toggle")
        self.m.key_event("ctrl", True)
        self.m.key_event("r", True)
        self.assertEqual(self.records, [("toggle", "ctrl+r")])
        self.assertEqual(self.fired, [])  # waehrend der Aufnahme loest nichts aus
        self.assertIsNone(self.m.recording)

    def test_record_modifier_alone_and_escape(self):
        self.m.start_recording("stop")
        self.m.key_event("shift", True)
        self.m.key_event("shift", False)
        self.m.start_recording("stop")
        self.m.key_event("esc", True)
        self.m.start_recording("toggle")
        self.m.mouse_event("x2", True)
        self.assertEqual(self.records, [("stop", "shift"), ("stop", None), ("toggle", "mouse5")])


if __name__ == "__main__":
    unittest.main()
