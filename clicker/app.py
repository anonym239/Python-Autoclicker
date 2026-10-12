"""Verbindet Einstellungen, Klick-Engine, Hotkeys, Webserver und Fenster."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request

from . import APP_NAME, VERSION, WINDOW_TITLE
from .backend import create_backend
from .config import PRESET_ORDER, PRESETS, Config, user_data_dir
from .engine import ClickEngine
from .keys import HotkeyMatcher, normalize_hotkey
from .qrcodegen import QrCode
from .server import WebServer
from .window import open_app_window

RECORD_TIMEOUT = 15.0


def lan_ip() -> str | None:
    """IP-Adresse dieses PCs im WLAN/LAN (es wird nichts gesendet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def qr_svg(text: str) -> str:
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    n, border = qr.get_size(), 2
    parts = []
    for y in range(n):
        for x in range(n):
            if qr.get_module(x, y):
                parts.append(f"M{x + border},{y + border}h1v1h-1z")
    size = n + border * 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="#111"/></svg>')


class App:
    def __init__(self, folder: str, web_dir: str, demo: bool = False, keep_alive: bool = False):
        self.folder = folder
        self.config = Config(folder)
        self.config.load()
        self.backend = create_backend(force_demo=demo)
        self.engine = ClickEngine(self.backend)
        snap = self.config.snapshot()
        self.engine.lifetime_base = snap["stats"]["lifetime_clicks"]
        self.engine.on_event = self._on_engine_event
        self.matcher = HotkeyMatcher(self._on_hotkey, self._on_mouse, self._on_record)
        self.server = WebServer(self, web_dir, snap["general"]["port"])
        self.keep_alive = keep_alive          # Fenster schliessen beendet NICHT (Tests/--no-window)
        self.rev = 1                          # Konfig-Revision fuer die Oberflaeche
        self.recording = False
        self._record_deadline = 0.0
        self.notice = None
        self._notice_id = 0
        self.remote_error: str | None = None
        self._last_desktop_poll = 0.0
        self._bye_at = 0.0
        self._save_timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self.quit_event = threading.Event()
        self._shut = False
        if self.config.migrated_from:
            self._notify("Einstellungen aus v5 übernommen")

    # ─── Eigenschaften ──────────────────────────────────
    @property
    def token(self) -> str:
        return self.config.data["general"]["token"]

    def ping(self) -> dict:
        return {"app": APP_NAME, "version": VERSION}

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.server.port}/?t={self.token}"

    def remote_url(self) -> str | None:
        ip = lan_ip()
        return f"http://{ip}:{self.server.port}/?t={self.token}" if ip else None

    def remote_qr_svg(self) -> str:
        return qr_svg(self.remote_url() or self.local_url())

    # ─── Start / Ende ───────────────────────────────────
    def start(self) -> None:
        self.config.save()  # Handy-Code bleibt so ueber Neustarts gleich
        self._apply(initial=True)
        self.engine.start_threads()
        self.backend.start_input(self.matcher)
        host = "0.0.0.0" if self.config.data["general"]["remote"] else "127.0.0.1"
        self.server.start(host)
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()

    def shutdown(self) -> None:
        if self._shut:
            return
        self._shut = True
        self.quit_event.set()
        self.engine.shutdown()
        self._store_stats()
        self.config.save()
        self.backend.stop_input()
        self.server.stop()

    def _housekeeping(self) -> None:
        last_save = time.monotonic()
        saved_clicks = self.engine.lifetime_clicks()
        while not self.quit_event.wait(0.5):
            now = time.monotonic()
            if self.recording and now > self._record_deadline:
                self.matcher.cancel_recording()
                self.recording = False
            if self._bye_at and now - self._bye_at > 3.0:
                self._bye_at = 0.0
                if self._last_desktop_poll < now - 3.0 and not self.keep_alive:
                    self.quit_event.set()  # Fenster wurde geschlossen
            if now - last_save > 30 and self.engine.lifetime_clicks() != saved_clicks:
                self._store_stats()
                self.config.save()
                saved_clicks = self.engine.lifetime_clicks()
                last_save = now

    def _store_stats(self) -> None:
        with self.config._lock:
            st = self.config.data["stats"]
            st["lifetime_clicks"] = self.engine.lifetime_clicks()
            st["best_cps"] = max(st["best_cps"], round(self.engine.best_cps, 1))

    def _save_soon(self) -> None:
        with self._lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.8, self.config.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    # ─── Konfiguration anwenden ─────────────────────────
    def _apply(self, initial: bool = False) -> None:
        cfg = self.config
        self.engine.configure(cfg.click_settings(), cfg.smart_settings())
        self.matcher.set_bindings({"toggle": cfg.data["hotkey"]})
        need_mouse = cfg.mode() in ("hold_mouse", "boost") or self.matcher.wants_mouse_buttons()
        self.backend.set_mouse_hook(need_mouse)
        self.rev += 1
        if initial and cfg.data["general"]["always_on_top"]:
            threading.Thread(target=self._topmost_retry, daemon=True).start()

    def _topmost_retry(self) -> None:
        for _ in range(40):  # das Fenster braucht einen Moment
            if self.quit_event.wait(0.5):
                return
            if self.backend.set_topmost(WINDOW_TITLE, self.config.data["general"]["always_on_top"]):
                return

    def _notify(self, text: str) -> None:
        self._notice_id += 1
        self.notice = {"id": self._notice_id, "text": text, "at": time.time()}

    # ─── Ereignisse ─────────────────────────────────────
    def _on_hotkey(self, slot: str, down: bool) -> None:
        if slot != "toggle":
            return
        if self.config.mode() == "hold_key":
            self.engine.set_key_held(down)
        elif down:
            self.engine.toggle("hotkey")

    def _on_mouse(self, button: str, down: bool) -> None:
        self.engine.set_mouse_held(button, down)

    def _on_record(self, slot: str, text: str | None) -> None:
        with self._lock:
            self.recording = False
            if text:
                self.config.set_hotkey(text)
                self._notify(f"Hotkey gespeichert: {normalize_hotkey(text).upper()}")
                self._save_soon()
            self._apply()

    def _on_engine_event(self, event: str) -> None:
        if self.config.data["general"]["sound"]:
            self.backend.beep(event)
        if event == "limit":
            self._notify("Auto-Stopp erreicht")
        if event in ("stop", "limit"):
            self._store_stats()
            self._save_soon()

    # ─── API ────────────────────────────────────────────
    def state(self, remote: bool, since: str = "-1", client: str = "") -> dict:
        if not remote and client == "desktop":
            self._last_desktop_poll = time.monotonic()
        out = {
            "rev": self.rev,
            "engine": self.engine.status(),
            "recording": self.recording,
            "notice": self.notice if self.notice and time.time() - self.notice["at"] < 6 else None,
        }
        if str(since) != str(self.rev):
            snap = self.config.snapshot()
            general = {k: v for k, v in snap["general"].items() if k not in ("token", "port")}
            out["config"] = {
                "preset": snap["preset"],
                "presets": [{"id": pid, "name": PRESETS[pid]["name"], "mode": PRESETS[pid]["mode"]}
                            for pid in PRESET_ORDER],
                "mode": self.config.mode(),
                "current": self.config.current(),
                "hotkey": snap["hotkey"],
                "general": general,
                "best_cps_ever": max(snap["stats"]["best_cps"], round(self.engine.best_cps, 1)),
            }
            out["info"] = {
                "name": APP_NAME,
                "version": VERSION,
                "backend": self.backend.name,
                "hooks_ok": getattr(self.backend, "hooks_ok", self.backend.has_global_input),
                "remote_client": remote,
                "remote_url": self.remote_url() if snap["general"]["remote"] else None,
                "remote_error": self.remote_error,
            }
        return out

    def handle(self, name: str, body: dict, remote: bool = False, client: str = ""):
        if name == "action":
            return self.action(body.get("do"), "remote" if remote else "ui")
        if name == "settings":
            general = body.get("general") or {}
            if remote:  # Fenster-Optionen nur am PC
                general.pop("always_on_top", None)
            changed = self.config.update(body)
            if "general" in changed and "always_on_top" in general:
                self.backend.set_topmost(WINDOW_TITLE, self.config.data["general"]["always_on_top"])
            self._apply()
            self._save_soon()
            return self.state(remote)
        if name == "preset":
            if not self.config.select(str(body.get("id", ""))):
                return {"error": "Unbekannter Modus"}
            self._apply()
            self._save_soon()
            return self.state(remote)
        if name == "record":
            return self.record(body, remote)
        if name == "remote":
            if remote:
                return {"error": "Nur am PC änderbar"}
            return self.set_remote(body)
        if name == "bye":
            if not remote and client == "desktop":
                self._bye_at = time.monotonic()
            return {"ok": True}
        return None

    def action(self, do, source: str):
        if do == "toggle":
            self.engine.toggle(source)
        elif do == "stop":
            self.engine.stop("manual")
        elif do == "reset_stats":
            self.engine.reset_stats()
        else:
            return {"error": "Unbekannte Aktion"}
        return self.state(source == "remote")

    def record(self, body: dict, remote: bool = False):
        if body.get("cancel"):
            self.matcher.cancel_recording()
            self.recording = False
            self._apply()
            return self.state(remote)
        key = body.get("key")
        if key is not None:
            # Taste kommt aus dem Browser – nur ohne globale Hooks (Demo-Modus)
            if self.backend.has_global_input:
                return self.state(remote)
            text = normalize_hotkey(str(key))
            if not text:
                return {"error": "Diese Taste geht leider nicht"}
            self.matcher.stop_recording()
            self._on_record("toggle", text)
            return self.state(remote)
        self.recording = True
        self._record_deadline = time.monotonic() + RECORD_TIMEOUT
        self.matcher.start_recording("toggle")
        self._apply()
        return self.state(remote)

    def set_remote(self, body: dict):
        if body.get("new_token"):
            self.config.new_token()
            self._notify("Neuer Code – das Handy muss den QR-Code neu scannen")
        if "enabled" in body:
            on = bool(body["enabled"])
            self.config.data["general"]["remote"] = on
            err = self.server.rebind("0.0.0.0" if on else "127.0.0.1")
            self.remote_error = err
            if err:
                self.config.data["general"]["remote"] = False
        self.rev += 1
        self._save_soon()
        return self.state(False)


# ─── Programmstart ──────────────────────────────────────
def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.6) as r:
            return json.loads(r.read().decode()).get("app") == APP_NAME
    except Exception:
        return False


def _paths() -> tuple[str, str, str]:
    """-> (Programmordner, web-Ordner, Einstellungs-Ordner)"""
    if getattr(sys, "frozen", False):  # installierte .exe
        bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        root = os.path.dirname(sys.executable)
        return root, os.path.join(bundle, "web"), user_data_dir(root)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return root, os.path.join(root, "web"), root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autoclicker", description=f"{APP_NAME} {VERSION}")
    parser.add_argument("--demo", action="store_true", help="Demo-Modus: simuliert Klicks (zum Ausprobieren)")
    parser.add_argument("--no-window", action="store_true", help="kein Fenster öffnen (nur Server)")
    parser.add_argument("--browser", action="store_true", help="im Standardbrowser statt als App-Fenster öffnen")
    parser.add_argument("--port", type=int, help="Port für Oberfläche/Handy (Standard 8765)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Umlaute dürfen den Start nie abbrechen
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass

    root, web_dir, data_dir = _paths()
    app = App(data_dir, web_dir, demo=args.demo, keep_alive=args.no_window)
    if args.port:
        app.server.port = args.port

    if _already_running(app.server.port):
        print(f"{APP_NAME} läuft bereits – das Fenster wird nach vorne geholt.")
        app.backend.focus_window(WINDOW_TITLE)
        return 0
    app.backend.claim_instance()

    try:
        app.start()
    except OSError as e:
        print(f"Start fehlgeschlagen: {e}")
        return 1

    print(f"{APP_NAME} {VERSION} ({'Demo' if app.backend.name == 'demo' else 'Windows'})")
    print(f"Oberfläche: {app.local_url()}")
    print("Beenden: Fenster schließen oder hier Strg+C")
    if app.backend.name == "windows" and not getattr(app.backend, "hooks_ok", True):
        print("WARNUNG: Globale Hotkeys konnten nicht aktiviert werden.")

    if not args.no_window:
        proc = open_app_window(app.local_url() + "&client=desktop", data_dir, use_browser=args.browser)
        if proc is not None:
            threading.Thread(target=_watch_window, args=(app, proc), daemon=True).start()

    try:
        while not app.quit_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    app.shutdown()
    return 0


def _watch_window(app: App, proc) -> None:
    started = time.monotonic()
    proc.wait()
    # Sehr kurze Laufzeit = Browser hat an ein anderes Fenster uebergeben -> ignorieren
    if time.monotonic() - started > 5 and not app.keep_alive:
        app.quit_event.set()


if __name__ == "__main__":
    sys.exit(main())
