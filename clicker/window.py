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

WINDOW_SIZE = (860, 680)  # passt ohne Scrollen, auch mit Update-Hinweis


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
    path = os.path.join(base, "AutoClicker", "window") if base else \
        os.path.join(fallback_folder, ".window-profile")
    os.makedirs(path, exist_ok=True)
    return path


WEBVIEW2_RUNTIME = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_ready() -> bool:
    """Sind .NET 4.6.2+ und die WebView2-Runtime da? (nur Registry lesen)

    Wichtig: vorher pruefen – ohne .NET stuerzt pythonnet beim Import hart ab,
    das liesse sich nicht mehr abfangen.
    """
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
            if int(winreg.QueryValueEx(k, "Release")[0]) < 394802:
                return False
    except OSError:
        return False
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients")):
        try:
            with winreg.OpenKey(root, path + "\\" + WEBVIEW2_RUNTIME) as k:
                version = str(winreg.QueryValueEx(k, "pv")[0])
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return True
    return False


def run_native_window(url: str, title: str, on_top: bool, icon: str = "", on_ready=None) -> bool:
    """Eigenes Programmfenster (WebView2, in Windows 10/11 eingebaut).

    Im Task-Manager steht dann AutoClicker.exe mit eigenem Icon – kein Chrome/Edge.
    Blockiert, bis das Fenster geschlossen wird. -> False, wenn es nicht geht
    (pywebview fehlt oder WebView2 ist nicht installiert) – dann wird der
    Browser-Weg benutzt.
    """
    if not webview2_ready():
        return False
    try:
        import webview  # pywebview
        from webview.platforms import winforms
    except Exception:
        return False
    if getattr(winforms, "renderer", "") != "edgechromium":
        return False  # ohne WebView2 nimmt pywebview den alten Internet Explorer – den wollen wir nicht
    try:
        w, h = WINDOW_SIZE
        win = webview.create_window(title, url, width=w, height=h, min_size=(760, 600), on_top=on_top)
        if on_ready:
            on_ready(win)
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        webview.start(gui="edgechromium", private_mode=False, icon=icon or None,
                      storage_path=os.path.join(base, "AutoClicker", "webview"))
        return True
    except Exception:
        return False


def open_web_window(url: str, title: str) -> bool:
    """Webseite (z. B. YouTube) in einem weiteren eigenen Fenster oeffnen. Es teilt sich
    WebView2 und das Profil mit dem AutoClicker-Fenster: Anmeldungen bleiben lokal auf dem
    PC gespeichert. -> False, wenn kein eigenes Fenster laeuft (dann Standardbrowser)."""
    try:
        import webview  # pywebview
        if not webview.windows:
            return False
        webview.create_window(title, url, width=1200, height=800, min_size=(400, 300))
        return True
    except Exception:
        return False


def close_all_windows() -> None:
    """Programm wird beendet: auch die Webseiten-Fenster schliessen."""
    try:
        import webview
        for win in list(webview.windows):
            try:
                win.destroy()
            except Exception:
                pass
    except Exception:
        pass


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
