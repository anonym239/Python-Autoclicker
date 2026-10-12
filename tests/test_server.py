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

    def test_action_starts_countdown(self):
        code, body = self.req("/api/action", {"do": "toggle"})
        self.assertEqual(code, 200)
        time.sleep(0.05)
        _, body = self.req("/api/state")
        self.assertIsNotNone(json.loads(body)["engine"]["countdown"])
        self.req("/api/action", {"do": "stop"})
        code, body = self.req("/api/action", {"do": "explode"})
        self.assertEqual(code, 400)

    def test_presets_and_record(self):
        code, body = self.req("/api/preset", {"id": "boost"})
        self.assertEqual(json.loads(body)["config"]["mode"], "boost")
        code, body = self.req("/api/preset", {"id": "nope"})
        self.assertEqual(code, 400)
        self.req("/api/preset", {"id": "standard"})
        code, body = self.req("/api/record", {})
        self.assertTrue(json.loads(body)["recording"])
        code, body = self.req("/api/record", {"key": "ctrl+x"})
        st = json.loads(body)
        self.assertEqual(st["config"]["hotkey"], "ctrl+x")
        self.assertFalse(st["recording"])
        self.req("/api/record", {})
        self.req("/api/record", {"key": "f6"})

    def test_static_files_and_traversal(self):
        code, body = self.req("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"AutoClicker", body)
        for path in ("/../clicker/app.py", "/%2e%2e/clicker/app.py", "/app.py", "/fonts/../../autoclicker.py"):
            code, _ = self.req(path, token=False)
            self.assertEqual(code, 404, path)
        code, body = self.req("/api/qr.svg")
        self.assertEqual(code, 200)
        self.assertTrue(body.startswith(b"<svg"))

    def test_bad_json(self):
        r = urllib.request.Request(self.base + "/api/settings", data=b"{nope",
                                   headers={"X-Token": self.app.token})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r, timeout=3)
        self.assertEqual(cm.exception.code, 400)

    def test_remote_toggle_rebinds(self):
        code, body = self.req("/api/remote", {"enabled": True})
        st = json.loads(body)
        self.assertEqual(code, 200)
        self.assertTrue(st["config"]["general"]["remote"])
        self.assertEqual(self.app.server.host, "0.0.0.0")
        time.sleep(0.1)
        code, body = self.req("/api/remote", {"enabled": False})
        self.assertFalse(json.loads(body)["config"]["general"]["remote"])
        self.assertEqual(self.app.server.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
