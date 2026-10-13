import os
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from clicker import updater
from clicker.app import App
from clicker.updater import Updater, find_latest, is_newer

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def release(tag, setup_version, draft=False, prerelease=False, host="https://github.com/"):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease,
            "html_url": f"https://github.com/x/y/releases/tag/{tag}", "body": "Neu",
            "assets": [{"name": f"AutoClicker-Setup-{setup_version}.exe", "size": 123,
                        "browser_download_url": f"{host}x/y/releases/download/{tag}/a.exe"},
                       {"name": f"AutoClicker-{setup_version}-portable.zip", "size": 5,
                        "browser_download_url": f"{host}x/y/z.zip"}]}


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(is_newer("6.3", "6.2"))
        self.assertTrue(is_newer("6.10", "6.9"))
        self.assertFalse(is_newer("6.2", "6.2"))
        self.assertFalse(is_newer("6.2.0", "6.2"))
        self.assertFalse(is_newer("6.0.0", "6.2"))

    def test_version_comes_from_setup_file_not_tag(self):
        # Das alte Release "v7.0.0" enthaelt in Wahrheit Version 6.0.0
        rels = [release("v7.0.0", "6.0.0"), release("v6.3", "6.3"),
                release("v9.0", "9.0", draft=True), release("v8.0", "8.0", prerelease=True),
                release("v9.9", "9.9", host="https://evil.example/")]
        latest = find_latest(rels)
        self.assertEqual(latest["version"], "6.3")
        self.assertFalse(is_newer(find_latest([release("v7.0.0", "6.0.0")])["version"], "6.2"))
        self.assertIsNone(find_latest("kaputt"))


class UpdaterTests(unittest.TestCase):
    def test_check_and_offline(self):
        data = [[release("v6.3", "6.3")]]
        u = Updater("6.2", fetch=lambda: data[0])
        self.assertEqual(u.check()["version"], "6.3")

        def offline():
            raise OSError("kein Internet")
        u._fetch = offline
        self.assertEqual(u.check()["version"], "6.3")  # bleibt bekannt
        u._fetch = lambda: [release("v6.2", "6.2")]
        self.assertIsNone(u.check())

    def test_download_checks_and_starts_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.exe")
            with open(good, "wb") as f:
                f.write(b"MZ" + b"\0" * 998)
            with open(os.path.join(tmp, "bad.exe"), "wb") as f:
                f.write(b"<html>" + b"\0" * 994)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=tmp))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}/"
            try:
                calls = []
                u = Updater("6.2")
                u.available = {"version": "6.3", "url": base + "good.exe", "size": 1000}
                with mock.patch.object(updater.subprocess, "Popen") as popen:
                    self.assertTrue(u.install(lambda: calls.append("before"), lambda: calls.append("after")))
                    self.assertFalse(u.install(lambda: None, lambda: None))  # laeuft schon
                    end = time.time() + 5
                    while "after" not in calls and time.time() < end:
                        time.sleep(0.02)
                    self.assertEqual(calls, ["before", "after"])
                    args = popen.call_args[0][0]
                    self.assertTrue(args[0].endswith("AutoClicker-Setup-6.3.exe"))
                    self.assertIn("/SILENT", args)
                self.assertEqual(u.status, "installing")

                u2 = Updater("6.2")
                u2.available = {"version": "6.3", "url": base + "bad.exe", "size": 1000}
                with mock.patch.object(updater.subprocess, "Popen") as popen:
                    u2.install(lambda: None, lambda: None)
                    end = time.time() + 5
                    while u2.status == "downloading" and time.time() < end:
                        time.sleep(0.02)
                    popen.assert_not_called()
                self.assertEqual(u2.status, "error")
            finally:
                httpd.shutdown()
                httpd.server_close()


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name, WEB, demo=True, keep_alive=True)
        self.app.updater = Updater("6.2", fetch=lambda: [release("v6.3", "6.3")])

    def tearDown(self):
        self.tmp.cleanup()

    def test_hidden_without_update(self):
        self.app.updater = Updater("6.2", fetch=lambda: [release("v7.0.0", "6.0.0")])
        self.app.updater.check()
        self.assertIsNone(self.app.state()["update"])

    def test_later_hides_for_five_days(self):
        self.app.updater.check()
        self.assertEqual(self.app.state()["update"]["version"], "6.3")
        self.app.update_action("later")
        self.assertIsNone(self.app.state()["update"])
        until = self.app.config.data["general"]["update_snooze_until"]
        self.assertAlmostEqual(until - time.time(), 5 * 24 * 3600, delta=60)
        self.app.config.data["general"]["update_snooze_until"] = time.time() - 1  # 5 Tage vorbei
        self.assertEqual(self.app.state()["update"]["version"], "6.3")

    def test_skip_hides_this_version_only(self):
        self.app.updater.check()
        self.app.update_action("skip")
        self.assertIsNone(self.app.state()["update"])
        self.app.updater._fetch = lambda: [release("v6.4", "6.4")]
        self.app.updater.check()
        self.assertEqual(self.app.state()["update"]["version"], "6.4")

    def test_install_from_source_opens_download_page(self):
        self.app.updater.check()
        self.assertFalse(self.app.state()["update"]["can_install"])
        with mock.patch("clicker.app.webbrowser.open") as wb:
            self.app.update_action("install")
            wb.assert_called_once()


if __name__ == "__main__":
    unittest.main()
