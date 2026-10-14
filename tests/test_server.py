import json
import os
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from clicker.app import App

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = App(cls.tmp.name, WEB, demo=True, keep_alive=True)
        cls.app.server.port = free_port()
        cls.app.start()
        cls.base = f"http://127.0.0.1:{cls.app.server.port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.tmp.cleanup()

    def req(self, path, body=None, token=True):
        headers = {"X-Token": self.app.token} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=3) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_token_required(self):
        code, _ = self.req("/api/state", token=False)
        self.assertEqual(code, 403)
        code, _ = self.req("/api/action", {"do": "toggle"}, token=False)
        self.assertEqual(code, 403)
        code, body = self.req("/api/ping", token=False)
        self.assertEqual(json.loads(body)["app"], "AutoClicker")

    def test_state_and_settings(self):
        code, body = self.req("/api/state")
        st = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(st["info"]["backend"], "demo")
        self.assertNotIn("token", st["config"]["general"])
        self.assertEqual([p["id"] for p in st["config"]["presets"]], ["standard", "pvp", "boost", "afk"])
        code, body = self.req(f"/api/state?since={st['rev']}")
        self.assertNotIn("config", json.loads(body))
        code, body = self.req("/api/settings", {"preset": {"cps": 12, "button": "right"}})
        cur = json.loads(body)["config"]["current"]
        self.assertEqual((cur["cps"], cur["button"]), (12, "right"))
        self.req("/api/settings", {"preset": {"cps": 10, "button": "left"}})

    def test_action_starts_immediately(self):
        code, body = self.req("/api/action", {"do": "toggle"})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["engine"]["armed"])
        code, body = self.req("/api/action", {"do": "stop"})
        self.assertFalse(json.loads(body)["engine"]["armed"])
        code, body = self.req("/api/action", {"do": "explode"})
        self.assertEqual(code, 400)

    def test_stop_reasons_and_hotkey(self):
        self.req("/api/action", {"do": "toggle"})
        code, body = self.req("/api/action", {"do": "toggle"})
        self.assertEqual(json.loads(body)["engine"]["stop_reason"], "button")
        # per Hotkey an und wieder aus -> die App weiss, welcher Hotkey es war
        self.app._on_hotkey("0", True)
        self.assertTrue(self.app.engine.armed)
        self.app._on_hotkey("0", True)
        code, body = self.req("/api/state")
        st = json.loads(body)
        self.assertEqual(st["engine"]["stop_reason"], "hotkey")
        self.assertEqual(st["stop_key"], self.app.config.hotkeys()[0]["key"])

    def test_learn_hotkey(self):
        self.req("/api/preset", {"id": "standard"})
        self.req("/api/settings", {"general": {"learn_hotkey_on": True}})
        self.assertEqual(self.app.matcher._bindings["learn"].key, "f7")
        # Taste aendern
        code, body = self.req("/api/hotkeys", {"op": "record", "target": "learn"})
        self.assertEqual(json.loads(body)["recording"], "learn")
        code, body = self.req("/api/hotkeys", {"op": "key", "key": "f8"})
        self.assertEqual(json.loads(body)["config"]["general"]["learn_hotkey"], "f8")
        # schon belegt
        self.req("/api/hotkeys", {"op": "record", "target": "learn"})
        self.req("/api/hotkeys", {"op": "key", "key": self.app.config.hotkeys()[0]["key"]})
        self.assertEqual(self.app.config.learn_hotkey(), "f8")
        # im Standard-Modus geht Anlernen nicht
        self.app._on_hotkey("learn", True)
        self.assertFalse(self.app.learning)
        self.assertEqual(self.app.notice["key"], "e_learn_mode")
        # PvP: an, nochmal druecken = abbrechen
        self.req("/api/preset", {"id": "pvp"})
        self.app._on_hotkey("learn", True)
        self.assertTrue(self.app.learning)
        self.app._on_hotkey("learn", True)
        self.assertFalse(self.app.learning)
        self.req("/api/settings", {"general": {"learn_hotkey_on": False}})
        self.assertNotIn("learn", self.app.matcher._bindings)
        self.req("/api/preset", {"id": "standard"})

    def test_presets_and_hotkeys(self):
        self.req("/api/action", {"do": "toggle"})
        code, body = self.req("/api/preset", {"id": "boost"})
        st = json.loads(body)
        self.assertEqual(st["config"]["mode"], "boost")
        self.assertFalse(st["engine"]["armed"])  # Moduswechsel stoppt den Klicker
        self.assertEqual(st["engine"]["stop_reason"], "mode")
        code, body = self.req("/api/preset", {"id": "nope"})
        self.assertEqual(code, 400)
        self.req("/api/preset", {"id": "standard"})
        # neuen Hotkey aufnehmen (im Demo-Modus kommt die Taste aus dem Browser)
        code, body = self.req("/api/hotkeys", {"op": "record"})
        self.assertEqual(json.loads(body)["recording"], "new")
        code, body = self.req("/api/hotkeys", {"op": "key", "key": "ctrl+x"})
        st = json.loads(body)
        self.assertIsNone(st["recording"])
        self.assertEqual(st["config"]["hotkeys"][-1], {"key": "ctrl+x", "action": "toggle"})
        idx = len(st["config"]["hotkeys"]) - 1
        code, body = self.req("/api/hotkeys", {"op": "action", "index": idx, "action": "off"})
        self.assertEqual(json.loads(body)["config"]["hotkeys"][idx]["action"], "off")
        code, body = self.req("/api/hotkeys", {"op": "delete", "index": idx})
        self.assertNotIn("ctrl+x", [h["key"] for h in json.loads(body)["config"]["hotkeys"]])
        code, body = self.req("/api/hotkeys", {"op": "delete", "index": 99})
        self.assertEqual(code, 400)

    def test_static_files_and_traversal(self):
        code, body = self.req("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"AutoClicker", body)
        for path in ("/../clicker/app.py", "/%2e%2e/clicker/app.py", "/app.py", "/fonts/../../autoclicker.py"):
            code, _ = self.req(path, token=False)
            self.assertEqual(code, 404, path)

    def test_bad_json(self):
        r = urllib.request.Request(self.base + "/api/settings", data=b"{nope",
                                   headers={"X-Token": self.app.token})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r, timeout=3)
        self.assertEqual(cm.exception.code, 400)


if __name__ == "__main__":
    unittest.main()


class WindowCloseTests(unittest.TestCase):
    def test_bye_only_closes_the_browser_window(self):
        """Eigenes Programmfenster: Schliessen beendet das Programm direkt – ein "bye"
        der Oberflaeche (z. B. beim Neuladen) beendet nie etwas. Browser-Weg: schon."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, WEB, demo=True, keep_alive=False)
            app.window_kind = "native"
            app.handle("bye", {}, client="desktop")
            self.assertFalse(app._window_closed(time.monotonic() + 10))
            app.window_kind = "browser"
            app.handle("bye", {}, client="desktop")
            self.assertTrue(app._window_closed(time.monotonic() + 10))


class MenuPauseTests(unittest.TestCase):
    def test_no_clicks_in_minecraft_menus(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, WEB, demo=True, keep_alive=True)
            app.start()
            b = app.backend
            try:
                app.handle("preset", {"id": "pvp"})
                app.engine.start()
                app._on_mouse("left", True)

                def clicks(secs=0.4):
                    c0 = b.clicks
                    time.sleep(secs)
                    return b.clicks - c0, app.engine.status()["reason"]

                b.foreground, b.cursor = "Minecraft 1.21.4", False     # im Spiel
                self.assertGreater(clicks()[0], 2)
                b.cursor = True                                        # E gedrueckt: Inventar offen
                time.sleep(0.1)
                self.assertEqual(clicks(), (0, "menu"))
                b.foreground = "Lunar Client 1.8.9 (v2.23.3)"          # auch in Lunar & Co.
                time.sleep(0.1)
                self.assertEqual(clicks(), (0, "menu"))
                b.cursor = False                                       # Inventar zu -> klickt wieder
                time.sleep(0.1)
                self.assertGreater(clicks()[0], 2)
                b.foreground, b.cursor = "Editor", True                # anderes Fenster: wie bisher
                time.sleep(0.1)
                self.assertGreater(clicks()[0], 2)
                app.handle("settings", {"general": {"menu_pause": False}})   # abschaltbar
                b.foreground = "Minecraft 1.21.4"
                time.sleep(0.1)
                self.assertGreater(clicks()[0], 2)
            finally:
                app._on_mouse("left", False)
                app.shutdown()
