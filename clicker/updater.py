"""Update-Pruefung ueber GitHub-Releases + Selbst-Update der installierten .exe.

- Prueft beim Start (nach ein paar Sekunden) und danach alle 6 Stunden.
- Massgeblich ist die Version im Dateinamen des Installers
  (AutoClicker-Setup-6.3.exe), nicht der Name des Release-Tags.
- "Jetzt aktualisieren": Installer herunterladen, Groesse pruefen, leise
  installieren lassen; der Installer startet den AutoClicker danach neu.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

REPO = "anonym239/Python-Autoclicker"
API_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
# Nur zum Testen: andere Update-Quelle (dann sind auch andere Download-Adressen erlaubt)
TEST_FEED = os.environ.get("AUTOCLICKER_UPDATE_FEED", "")
CHECK_EVERY = 6 * 3600
SNOOZE_SECONDS = 5 * 24 * 3600   # "In 5 Tagen erinnern"
SETUP_RE = re.compile(r"^AutoClicker-Setup-(\d+(?:\.\d+){0,3})\.exe$", re.IGNORECASE)


def parse_version(text) -> tuple | None:
    m = re.search(r"(\d+(?:\.\d+){0,3})", str(text or ""))
    if not m:
        return None
    nums = [int(x) for x in m.group(1).split(".")]
    return tuple((nums + [0, 0, 0])[:4])


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


def find_latest(releases) -> dict | None:
    """Neuestes Release mit Installer (Version aus dem Dateinamen)."""
    best = None
    for rel in releases if isinstance(releases, list) else []:
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        for asset in rel.get("assets") or []:
            m = SETUP_RE.match(str(asset.get("name", "")))
            url = str(asset.get("browser_download_url", ""))
            if not m or not (url.startswith("https://github.com/") or TEST_FEED):
                continue
            info = {"version": m.group(1), "url": url, "size": int(asset.get("size") or 0),
                    "page": rel.get("html_url") or f"https://github.com/{REPO}/releases",
                    "notes": str(rel.get("body") or "")[:600]}
            if best is None or parse_version(info["version"]) > parse_version(best["version"]):
                best = info
    return best


def _fetch_json(url: str, user_agent: str):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


class Updater:
    def __init__(self, current: str, fetch=None):
        self.current = current
        self._fetch = fetch or (lambda: _fetch_json(TEST_FEED or API_URL, f"AutoClicker/{current}"))
        self.available: dict | None = None
        self.status = "idle"        # idle | downloading | installing | error
        self.progress = 0.0
        self.error = ""
        self._lock = threading.Lock()

    def check(self) -> dict | None:
        try:
            latest = find_latest(self._fetch())
        except Exception:
            return self.available  # offline o. Ae. -> einfach spaeter nochmal
        with self._lock:
            self.available = latest if latest and is_newer(latest["version"], self.current) else None
        return self.available

    def run_checks(self, quit_event: threading.Event, first_delay: float = 4.0) -> None:
        def loop():
            if quit_event.wait(first_delay):
                return
            while True:
                self.check()
                if quit_event.wait(CHECK_EVERY):
                    return
        threading.Thread(target=loop, name="update-check", daemon=True).start()

    # ─── Selbst-Update ───────────────────────────────────
    def install(self, before_launch, after_launch) -> bool:
        """Laedt den Installer im Hintergrund und startet ihn. False = laeuft schon / nichts da."""
        with self._lock:
            if self.status in ("downloading", "installing") or not self.available:
                return False
            self.status, self.progress, self.error = "downloading", 0.0, ""
            info = dict(self.available)
        threading.Thread(target=self._install, args=(info, before_launch, after_launch),
                         name="update-install", daemon=True).start()
        return True

    def _install(self, info: dict, before_launch, after_launch) -> None:
        try:
            folder = tempfile.mkdtemp(prefix="AutoClicker-Update-")
            path = os.path.join(folder, f"AutoClicker-Setup-{info['version']}.exe")
            req = urllib.request.Request(info["url"], headers={"User-Agent": f"AutoClicker/{self.current}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.get("size") or 0)
                done = 0
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress = min(1.0, done / total)
            if info.get("size") and done != info["size"]:
                raise OSError("Download unvollständig")
            with open(path, "rb") as f:
                if f.read(2) != b"MZ":
                    raise OSError("Download ist kein Windows-Programm")
            self.status, self.progress = "installing", 1.0
            before_launch()
            flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED, NEW_PROCESS_GROUP
            subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                             creationflags=flags, close_fds=True)
            time.sleep(0.5)
            after_launch()
        except Exception as e:
            self.status, self.error = "error", str(e) or "Update fehlgeschlagen"
