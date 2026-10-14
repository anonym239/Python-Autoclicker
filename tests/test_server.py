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

    def test_back_link_only_while_browsing(self):
        code, body = self.req("/back", token=False)
        self.assertEqual(code, 404)                  # nicht auf einer Webseite -> nichts passiert

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


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name, WEB, demo=True, keep_alive=True)

    def tearDown(self):
        self.app.shutdown()
        self.tmp.cleanup()

    def test_new_install_has_no_game_and_default_pins(self):
        st = self.app.state()
        g = st["config"]["general"]
        self.assertEqual(g["game"], "")             # -> Home-Menue fragt nach dem Spiel
        self.assertEqual(g["home_version"], "")
        self.assertIn("roblox", st["config"]["games"])
        self.assertEqual([p["name"] for p in st["config"]["pins"]], ["YouTube", "Spotify", "Discord", "Twitch"])

    def test_old_settings_keep_minecraft(self):
        from clicker.config import Config
        with open(os.path.join(self.tmp.name, "clicker_settings.json"), "w", encoding="utf-8") as f:
            json.dump({"general": {"sound": True}}, f)
        c = Config(self.tmp.name)
        c.load()
        self.assertEqual(c.game(), "minecraft")

    def test_pick_game_switches_names_and_tools(self):
        app = self.app
        app.handle("preset", {"id": "pvp"})
        app.engine.start()
        app.handle("settings", {"general": {"game": "roblox"}})
        self.assertFalse(app.engine.armed)              # anderes Spiel -> Klicker aus
        g = app.config.data["general"]
        self.assertEqual(g["game"], "roblox")
        self.assertEqual(g["window_match"], "Roblox")   # Fenstername wechselt mit
        self.assertFalse(app._minecraft())
        app._on_hotkey("learn", True)                   # Anlernen gibt es nur in Minecraft
        self.assertFalse(app.learning)
        app.handle("settings", {"general": {"window_match": "Mein Spiel"}})
        app.handle("settings", {"general": {"game": "minecraft"}})
        self.assertEqual(g["window_match"], "Mein Spiel")  # selbst geaendert -> bleibt
        app.handle("settings", {"general": {"game": "quatsch", "home_version": "6.18"}})
        self.assertEqual((g["game"], g["home_version"]), ("minecraft", "6.18"))

    def test_pins_and_open(self):
        app = self.app
        st = app.handle("home", {"op": "pin_add", "target": "roblox.com", "name": ""})
        self.assertEqual(st["config"]["pins"][-1], {"name": "Roblox", "url": "https://roblox.com"})
        st = app.handle("home", {"op": "pin_add", "target": "C:\\Spiele\\Spiel.exe", "name": "Mein Spiel"})
        self.assertEqual(st["config"]["pins"][-1], {"name": "Mein Spiel", "app": "C:\\Spiele\\Spiel.exe"})
        for bad in ("hallo welt", "cmd.exe", "javascript:alert(1)", "C:\\x\\a.bat", ""):
            self.assertEqual(app.handle("home", {"op": "pin_add", "target": bad}), {"error": "e_pin_target"}, bad)
        while len(app.config.pins()) < 12:
            app.handle("home", {"op": "pin_add", "target": "example.com"})
        self.assertEqual(app.handle("home", {"op": "pin_add", "target": "example.com"}), {"error": "e_max_pins"})
        # oeffnen: Pin, Adresse, Suche
        self.assertEqual(app.handle("home", {"op": "open", "index": 1}), {"ok": True})
        self.assertEqual(app.last_opened, "spotify:")    # Programm wird bevorzugt
        app.handle("home", {"op": "open", "text": "twitch.tv/papaplatte"})
        self.assertEqual(app.last_opened, "https://twitch.tv/papaplatte")
        app.handle("home", {"op": "open", "text": "beste roblox spiele"})
        self.assertEqual(app.last_opened, "https://www.google.com/search?q=beste+roblox+spiele")
        self.assertEqual(app.handle("home", {"op": "open", "index": 99}), {"error": "e_not_found"})
        st = app.handle("home", {"op": "pin_remove", "index": 0})
        self.assertNotIn("YouTube", [p["name"] for p in st["config"]["pins"]])
        app.config.save()
        from clicker.config import Config
        again = Config(self.tmp.name)
        again.load()
        self.assertEqual(again.pins(), app.config.pins())


class FakeWindow:
    """Ersatz fuer das pywebview-Fenster."""

    def __init__(self):
        self.loaded, self.js, self.url = [], [], ""

    def load_url(self, url):
        self.loaded.append(url)
        self.url = url

    def get_current_url(self):
        return self.url

    def evaluate_js(self, code):
        self.js.append(code)
        return self.profile if "avatar-btn" in code else None

    profile = None


class InAppBrowsingTests(unittest.TestCase):
    def test_websites_open_in_the_app_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, WEB, demo=True, keep_alive=False)
            win = FakeWindow()
            app.window_kind, app.native_window = "native", win
            self.assertEqual(app.handle("home", {"op": "open", "index": 0}), {"ok": True})   # YouTube
            self.assertEqual(win.loaded, ["https://www.youtube.com"])
            self.assertTrue(app.browsing)
            app.on_page_loaded()                         # Seite geladen -> Knopf zurueck
            self.assertIn("/back", win.js[-1])
            self.assertNotIn(app.token, win.js[-1])      # die Webseite bekommt den Code nie zu sehen
            app.handle("home", {"op": "signin"})
            self.assertTrue(win.loaded[-1].startswith("https://accounts.google.com/"))
            self.assertTrue(app.back_to_app())
            self.assertEqual(win.loaded[-1], app.local_url() + "&client=desktop#home")
            app.on_page_loaded()                         # eigene Oberflaeche: kein Knopf, wieder in der App
            self.assertEqual(len(win.js), 1)
            self.assertFalse(app.browsing)
            self.assertFalse(app.back_to_app())

    def test_opening_a_website_never_closes_the_app(self):
        """Fehler 6.19: Webseite geoeffnet -> Oberflaeche fragt noch einmal nach und meldet
        sich dann ab ("bye") -> nach 3 s war das Programm zu."""
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, WEB, demo=True, keep_alive=False)
            app.window_kind, app.native_window = "native", FakeWindow()
            app.handle("home", {"op": "signin"})
            app.state(client="desktop")                  # letzte Abfrage, bevor die Seite wechselt
            app.handle("bye", {}, client="desktop")      # Oberflaeche verlaesst die Seite
            now = time.monotonic()
            self.assertFalse(app._window_closed(now + 10))
            self.assertTrue(app.back_to_app())           # Zurueck-Knopf geht trotzdem
            # Browser-Weg (kein eigenes Fenster): Abmelden ohne Nachfragen = Fenster zu
            app.window_kind, app.browsing = "browser", False
            app.handle("bye", {}, client="desktop")
            self.assertTrue(app._window_closed(time.monotonic() + 10))

    def test_profile_picture_after_sign_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = App(tmp, WEB, demo=True, keep_alive=False)
            app.PROFILE_DELAYS = (0.01,)
            win = FakeWindow()
            app.window_kind, app.native_window = "native", win
            pic = "https://yt3.ggpht.com/abc=s88-c-k"
            win.profile = json.dumps({"pic": pic, "out": False})
            app.handle("home", {"op": "signin"})
            win.url = "https://www.youtube.com/"     # nach der Anmeldung -> YouTube
            app.on_page_loaded()
            for _ in range(100):
                if app.config.data["general"]["profile_pic"]:
                    break
                time.sleep(0.01)
            self.assertEqual(app.state()["config"]["general"]["profile_pic"], pic)
            # fremde Adressen werden nie uebernommen
            self.assertFalse(app.config.set_profile_pic("https://evil.example/x.png"))
            self.assertEqual(app.config.data["general"]["profile_pic"], pic)
            # abgemeldet ("Anmelden"-Knopf auf der Seite) -> Bild weg
            app.config.set_profile_pic(pic)
            win.profile = json.dumps({"pic": "", "out": True})
            app.on_page_loaded()
            for _ in range(100):
                if not app.config.data["general"]["profile_pic"]:
                    break
                time.sleep(0.01)
            self.assertEqual(app.config.data["general"]["profile_pic"], "")
            # andere Seiten (z. B. Twitch) werden nicht ausgelesen
            win.js.clear()
            win.url = "https://www.twitch.tv/"
            app.on_page_loaded()
            time.sleep(0.05)
            self.assertFalse(any("avatar-btn" in c for c in win.js))

