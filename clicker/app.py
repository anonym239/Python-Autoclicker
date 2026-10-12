"""Verbindet Einstellungen, Klick-Engine, Hotkeys, Webserver und Fenster."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request

from . import APP_NAME, VERSION, WINDOW_TITLE
from .backend import create_backend
from .config import PRESET_ORDER, PRESETS, Config, user_data_dir
from .engine import ClickEngine
from .keys import HotkeyMatcher
from .server import WebServer
from .window import open_app_window

RECORD_TIMEOUT = 15.0
NEW = "new"  # Aufnahme-Ziel fuer einen neuen Hotkey


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
        self.recording = None                 # None | NEW | Index des Hotkeys
        self._record_deadline = 0.0
        self.notice = None
        self._notice_id = 0
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

    # ─── Start / Ende ───────────────────────────────────
    def start(self) -> None:
        self.config.save()
        self._apply(initial=True)
        self.engine.start_threads()
        self.backend.start_input(self.matcher)
        self.server.start()
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
            if self.recording is not None and now > self._record_deadline:
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
        self.matcher.set_bindings({str(i): h["key"] for i, h in enumerate(cfg.hotkeys())})
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
        if not down:
            return
        hks = self.config.hotkeys()
        try:
            action = hks[int(slot)]["action"]
        except (ValueError, IndexError):
            return
        if action == "on":
            self.engine.start()
        elif action == "off":
            self.engine.stop("manual")
        else:
            self.engine.toggle()

    def _on_mouse(self, button: str, down: bool) -> None:
        self.engine.set_mouse_held(button, down)

    def _on_record(self, slot: str, text: str | None) -> None:
        with self._lock:
            target = self.recording
            self.recording = None
            if text:
                err = self.config.set_hotkey(None if target == NEW else target, text)
                if err:
                    self._notify(err)
                else:
                    self._notify("Hotkey gespeichert")
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
    def state(self, since: str = "-1", client: str = "") -> dict:
        if client == "desktop":
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
                "hotkeys": snap["hotkeys"],
                "general": general,
            }
            out["info"] = {
                "name": APP_NAME,
                "version": VERSION,
                "backend": self.backend.name,
                "hooks_ok": getattr(self.backend, "hooks_ok", self.backend.has_global_input),
            }
        return out

    def handle(self, name: str, body: dict, client: str = ""):
        if name == "action":
            return self.action(body.get("do"))
        if name == "settings":
            general = body.get("general") or {}
            changed = self.config.update(body)
            if "general" in changed and "always_on_top" in general:
                self.backend.set_topmost(WINDOW_TITLE, self.config.data["general"]["always_on_top"])
            self._apply()
            self._save_soon()
            return self.state()
        if name == "preset":
            if not self.config.select(str(body.get("id", ""))):
                return {"error": "Unbekannter Modus"}
            self._apply()
            self._save_soon()
            return self.state()
        if name == "hotkeys":
            return self.hotkeys(body)
        if name == "bye":
            if client == "desktop":
                self._bye_at = time.monotonic()
            return {"ok": True}
        return None

    def action(self, do):
        if do == "toggle":
            self.engine.toggle()
        elif do == "stop":
            self.engine.stop("manual")
        elif do == "reset_stats":
            self.engine.reset_stats()
        else:
            return {"error": "Unbekannte Aktion"}
        return self.state()

    def hotkeys(self, body: dict):
        op = body.get("op")
        index = body.get("index")
        if index is not None and not isinstance(index, int):
            return {"error": "Ungültiger Hotkey"}
        if op == "record":  # naechste Taste aufnehmen (index None = neuer Hotkey)
            self.recording = NEW if index is None else index
            self._record_deadline = time.monotonic() + RECORD_TIMEOUT
            self.matcher.start_recording("record")
        elif op == "cancel":
            self.matcher.stop_recording()
            self.recording = None
        elif op == "key":
            # Taste kommt aus dem Browser – nur ohne globale Hooks (Demo-Modus)
            if self.backend.has_global_input or self.recording is None:
                return self.state()
            self.matcher.stop_recording()
            self._on_record("record", str(body.get("key", "")) or None)
            return self.state()
        elif op == "action":
            if not self.config.set_hotkey_action(index if index is not None else -1, str(body.get("action"))):
                return {"error": "Ungültige Aktion"}
            self._save_soon()
        elif op == "delete":
            if not self.config.delete_hotkey(index if index is not None else -1):
                return {"error": "Hotkey nicht gefunden"}
            self._save_soon()
        else:
            return {"error": "Unbekannte Aktion"}
        self._apply()
        return self.state()


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
    parser.add_argument("--port", type=int, help="Port für die Oberfläche (Standard 8765)")
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
