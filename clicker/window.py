"""Oeffnet die Oberflaeche als eigenes App-Fenster.

Microsoft Edge ist auf jedem Windows 10/11 installiert. Mit --app zeigt Edge
nur die Seite – ohne Tabs und Adressleiste, also wie ein normales Programm.
Fallback: Chrome/Brave, sonst der Standardbrowser.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser

WINDOW_SIZE = (980, 720)


def _candidates():
    env = os.environ.get
    roots = [env("PROGRAMFILES(X86)"), env("PROGRAMFILES"), env("LOCALAPPDATA")]
    rel = [
        r"Microsoft\Edge\Application\msedge.exe",
        r"Google\Chrome\Application\chrome.exe",
        r"BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for r in rel:  # Edge zuerst, dann Chrome, dann Brave
        for root in roots:
            if root:
                yield os.path.join(root, r)
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser", "brave"):
        found = shutil.which(name)
        if found:
            yield found


def find_browser() -> str | None:
    for path in _candidates():
        if path and os.path.isfile(path):
            return path
    return None


def profile_dir(fallback_folder: str) -> str:
    base = os.environ.get("LOCALAPPDATA")
    path = os.path.join(base, "AutoClickerV6", "window") if base else \
        os.path.join(fallback_folder, ".window-profile")
    os.makedirs(path, exist_ok=True)
    return path


def open_app_window(url: str, folder: str, use_browser: bool = False):
    """-> subprocess.Popen des App-Fensters oder None (Standardbrowser/Fehler)."""
    exe = None if use_browser else find_browser()
    if exe:
        w, h = WINDOW_SIZE
        args = [
            exe,
            f"--app={url}",
            f"--user-data-dir={profile_dir(folder)}",
            f"--window-size={w},{h}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
        ]
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            return subprocess.Popen(args, creationflags=flags,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    webbrowser.open(url)
    return None
