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

from . import APP_NAME, VERSION
from .backend import create_backend
from .config import HOTKEY_SLOTS, Config
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
        self.server = WebServer(self, web_dir, snap["app"]["port"])
        self.keep_alive = keep_alive          # Fenster schliessen beendet NICHT (Tests/--no-window)
        self.rev = 1                          # Konfig-Revision fuer die UI
        self.recording: str | None = None
        self._record_deadline = 0.0
        self.notice = None
        self._notice_id = 0
        self.remote_error: str | None = None
        self._last_desktop_poll = 0.0
        self._bye_at = 0.0
        self._save_timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self.quit_event = threading.Event()
        self._started = time.monotonic()
        if self.config.migrated_from:
            self._notify("Einstellungen aus v5 übernommen (Profil „Mein v5“)")

    # ─── Eigenschaften ──────────────────────────────────
    @property
    def token(self) -> str:
        return self.config.data["app"]["token"]

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
        self.config.save()  # Code fuers Handy bleibt so ueber Neustarts gleich
        self._apply(initial=True)
        self.engine.start_threads()
        self.backend.start_input(self.matcher)
        host = "0.0.0.0" if self.config.data["app"]["remote"] else "127.0.0.1"
        self.server.start(host)
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()

    def shutdown(self) -> None:
        if self.quit_event.is_set():
            return
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
                self.recording = None
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
        self.matcher.set_bindings(cfg.data["hotkeys"])
        need_mouse = cfg.active_profile()["mode"] == "hold_mouse" or self.matcher.wants_mouse_buttons()
        self.backend.set_mouse_hook(need_mouse)
        self.rev += 1
        if initial and cfg.data["app"]["always_on_top"]:
            threading.Thread(target=self._topmost_retry, daemon=True).start()

    def _topmost_retry(self) -> None:
        for _ in range(40):  # das Fenster braucht einen Moment
            if self.quit_event.wait(0.5):
                return
            if self.backend.set_topmost(APP_NAME, self.config.data["app"]["always_on_top"]):
                return

    def _notify(self, text: str, kind: str = "info") -> None:
        self._notice_id += 1
        self.notice = {"id": self._notice_id, "text": text, "kind": kind, "at": time.time()}

    # ─── Ereignisse ─────────────────────────────────────
    def _on_hotkey(self, slot: str, down: bool) -> None:
        mode = self.config.active_profile()["mode"]
        if slot == "toggle":
            if mode == "hold_key":
                self.engine.set_key_held(down)
            elif down:
                self.engine.toggle("hotkey")
        elif slot == "stop" and down:
            self.engine.stop("manual")
        elif slot == "next_profile" and down:
            self.profile_op({"op": "next"})
            if self.config.data["app"]["sound"]:
                self.backend.beep("profile")

    def _on_mouse(self, button: str, down: bool) -> None:
        self.engine.set_mouse_held(button, down)

    def _on_record(self, slot: str, text: str | None) -> None:
        with self._lock:
            self.recording = None
            if text:
                text = normalize_hotkey(text)
                for other in HOTKEY_SLOTS:  # doppelte Belegung aufloesen
                    if other != slot and self.config.data["hotkeys"].get(other) == text:
                        self.config.set_hotkey(other, "")
                self.config.set_hotkey(slot, text)
                self._notify(f"Hotkey gespeichert: {text.upper()}")
                self._save_soon()
            self._apply()

    def _on_engine_event(self, event: str) -> None:
        if self.config.data["app"]["sound"]:
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
            app = snap["app"]
            remote_on = app["remote"]
            out["config"] = {
                "active": snap["active"],
                "profiles": [p["name"] for p in snap["profiles"]],
                "profile": self.config.active_profile(),
                "hotkeys": snap["hotkeys"],
                "smart": snap["smart"],
                "app": {k: app[k] for k in ("sound", "always_on_top", "theme", "remote")},
                "best_cps_ever": max(snap["stats"]["best_cps"], round(self.engine.best_cps, 1)),
            }
            out["info"] = {
                "name": APP_NAME,
                "version": VERSION,
                "backend": self.backend.name,
                "hooks_ok": getattr(self.backend, "hooks_ok", self.backend.has_global_input),
                "remote_client": remote,
                "remote_url": self.remote_url() if remote_on else None,
                "remote_error": self.remote_error,
                "port": self.server.port,
            }
        return out

    def handle(self, name: str, body: dict, remote: bool = False, client: str = ""):
        if name == "action":
            return self.action(body.get("do"), "remote" if remote else "ui")
        if name == "settings":
            changed = self.config.update(body)
            if "app" in changed and "always_on_top" in (body.get("app") or {}):
                self.backend.set_topmost(APP_NAME, self.config.data["app"]["always_on_top"])
            self._apply()
            self._save_soon()
            return self.state(remote)
        if name == "profile":
            return self.profile_op(body, remote)
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
        elif do == "start":
            self.engine.start(source)
        elif do == "stop":
            self.engine.stop("manual")
        elif do == "reset_stats":
            self.engine.reset_stats()
        else:
            return {"error": "Unbekannte Aktion"}
        return self.state(source == "remote")

    def profile_op(self, body: dict, remote: bool = False):
        err = self.config.profile_op(str(body.get("op", "")), str(body.get("name", "")),
                                     str(body.get("new_name", "")))
        if err:
            return {"error": err}
        if body.get("op") == "next":
            self._notify(f"Profil: {self.config.data['active']}")
        self._apply()
        self._save_soon()
        return self.state(remote)

    def record(self, body: dict, remote: bool = False):
        if body.get("cancel"):
            self.matcher.cancel_recording()
            self.recording = None
            self._apply()
            return self.state(remote)
        slot = body.get("slot")
        if slot not in HOTKEY_SLOTS:
            return {"error": "Unbekannter Hotkey"}
        key = body.get("key")
        if key is not None:
            # Taste kommt aus dem Browser – nur ohne globale Hooks (Demo) oder zum Loeschen
            if key == "":
                self.config.set_hotkey(slot, "")
                self.matcher.cancel_recording()
                self.recording = None
                self._apply()
                self._save_soon()
                return self.state(remote)
            if self.backend.has_global_input:
                return self.state(remote)
            text = normalize_hotkey(str(key))
            if not text:
                return {"error": "Diese Taste wird nicht unterstützt"}
            self.matcher.stop_recording()
            self._on_record(slot, text)
            return self.state(remote)
        self.recording = slot
        self._record_deadline = time.monotonic() + RECORD_TIMEOUT
        self.matcher.start_recording(slot)
        self._apply()
        return self.state(remote)

    def set_remote(self, body: dict):
        if body.get("new_token"):
            self.config.new_token()
            self._notify("Neuer Handy-Code – das Handy muss den QR-Code neu scannen")
        if "enabled" in body:
            on = bool(body["enabled"])
            self.config.data["app"]["remote"] = on
            err = self.server.rebind("0.0.0.0" if on else "127.0.0.1")
            self.remote_error = err
            if err:
                self.config.data["app"]["remote"] = False
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autoclicker", description=f"{APP_NAME} – Block Edition")
    parser.add_argument("--demo", action="store_true", help="Demo-Modus: simuliert Klicks (zum Ausprobieren)")
    parser.add_argument("--no-window", action="store_true", help="kein Fenster oeffnen (nur Server)")
    parser.add_argument("--browser", action="store_true", help="im Standardbrowser statt als App-Fenster oeffnen")
    parser.add_argument("--port", type=int, help="Port fuer Oberflaeche/Handy (Standard 8765)")
    parser.add_argument("--remote", action="store_true", help="Handy-Fernbedienung sofort aktivieren")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Umlaute duerfen den Start nie abbrechen
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    web_dir = os.path.join(root, "web")
    app = App(root, web_dir, demo=args.demo, keep_alive=args.no_window)
    if args.port:
        app.server.port = args.port
    if args.remote:
        app.config.data["app"]["remote"] = True

    if _already_running(app.server.port):
        print(f"{APP_NAME} läuft bereits – das Fenster wird nach vorne geholt.")
        app.backend.focus_window(APP_NAME)
        return 0

    try:
        app.start()
    except OSError as e:
        print(f"Start fehlgeschlagen: {e}")
        return 1

    print("=" * 56)
    print(f"  {APP_NAME}  ({'Demo-Modus' if app.backend.name == 'demo' else 'Windows'})")
    print(f"  Oberfläche: {app.local_url()}")
    if app.config.data["app"]["remote"]:
        print(f"  Handy:       {app.remote_url()}")
    print("  Beenden: Fenster schließen oder hier Strg+C")
    print("=" * 56)
    if app.backend.name == "windows" and not getattr(app.backend, "hooks_ok", True):
        print("WARNUNG: Globale Hotkeys konnten nicht aktiviert werden.")

    proc = None
    if not args.no_window:
        proc = open_app_window(app.local_url() + "&client=desktop", root, use_browser=args.browser)
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
