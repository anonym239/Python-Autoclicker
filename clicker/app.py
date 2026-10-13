"""Verbindet Einstellungen, Klick-Engine, Hotkeys, Webserver und Fenster."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from . import APP_NAME, VERSION, WINDOW_TITLE
from .backend import create_backend
from .config import PRESET_ORDER, PRESETS, Config, user_data_dir
from .engine import ClickEngine
from .hotbar import (CAPTURE_GUI_H, MAX_SCALE, SAME_IOU, Shot, SlotTracker, best_match, item_sample, locate,
                     mask_from_hex, shot_png)
from .keys import HotkeyMatcher
from .server import WebServer
from .updater import SNOOZE_SECONDS, Updater
from .window import open_app_window, run_native_window

RECORD_TIMEOUT = 15.0
LEARN_TIMEOUT = 120.0   # so lange wartet "Werkzeug anlernen" auf das Abbauen im Spiel
TOOL_RECHECK = 0.12     # bei gedrueckter Maustaste so oft nachschauen, was in der Hand ist
TOOL_MODES = ("hold_mouse", "boost")
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
        self.updater = Updater(VERSION)
        self.can_self_update = bool(getattr(sys, "frozen", False)) and self.backend.name == "windows"
        self.native_window = None             # pywebview-Fenster, wenn vorhanden
        self.window_kind = ""                 # "native" | "browser" | ""
        self.icon_path = ""                   # assets/icon.ico (scharfes Taskleisten-Icon)
        self.keep_alive = keep_alive          # Fenster schliessen beendet NICHT (Tests/--no-window)
        self.rev = 1                          # Konfig-Revision fuer die Oberflaeche
        self.recording = None                 # None | NEW | Index des Hotkeys
        self.learning = False                 # "Werkzeug anlernen" laeuft
        self.learn_error = ""                 # letzter Fehlschlag beim Anlernen (Textschluessel)
        self._learn_deadline = 0.0
        self._learn_press = False
        self._learn_skipped = 0
        self._tool_masks: list = []           # Umrisse der angelernten Werkzeuge
        self._tool_btn_down = False
        self._tool_kick = threading.Event()
        self.tool_index = -1                  # welches Werkzeug gerade in der Hand ist
        self.hotbar_seen = None               # None = noch nicht geschaut
        self.slots = SlotTracker()            # Platz aus Tasten/Mausrad (falls der Rahmen nicht erkannt wird)
        self.backend.on_input = self._on_raw_input
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
            self._notify("n_migrated")

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
        if not self.keep_alive:  # nicht in Tests / --no-window
            self.updater.run_checks(self.quit_event)
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()
        threading.Thread(target=self._tool_loop, name="tools", daemon=True).start()

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
            if self.learning and now > self._learn_deadline:
                self.learning = False
                self._apply()
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
        need_mouse = cfg.mode() in TOOL_MODES or self.matcher.wants_mouse_buttons() or self.learning
        self.backend.set_mouse_hook(need_mouse)
        self._tool_masks = [mask_from_hex(t["mask"]) for t in cfg.tools()]
        if not self._tools_matter():
            self.tool_index = -1
            self.engine.set_tool(False)
        self.rev += 1
        if initial:
            threading.Thread(target=self._window_setup, daemon=True).start()

    def _window_setup(self) -> None:
        """Sobald das Fenster da ist: scharfes Icon + ggf. immer im Vordergrund."""
        want_icon = bool(self.icon_path) and os.path.isfile(self.icon_path)
        icon_hits, top_done = 0, False
        for _ in range(60):  # das Fenster braucht einen Moment
            if self.quit_event.wait(0.5):
                return
            if not top_done and self.config.data["general"]["always_on_top"]:
                top_done = self.backend.set_topmost(WINDOW_TITLE, True)
            if want_icon and self.backend.set_window_icon(WINDOW_TITLE, self.icon_path):
                icon_hits += 1  # Edge setzt sein Icon nach dem Laden evtl. neu -> ein paar Mal wiederholen
            icon_ok = not want_icon or icon_hits >= 6
            top_ok = top_done or not self.config.data["general"]["always_on_top"]
            if icon_ok and top_ok:
                return

    def _notify(self, key: str) -> None:
        """key = Textschluessel aus web/i18n.js (die Oberflaeche uebersetzt ihn)."""
        self._notice_id += 1
        self.notice = {"id": self._notice_id, "key": key, "at": time.time()}

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
        if self.learning and button == "left":
            self._learn_mouse(down)
        elif button == self.config.current()["button"] and self._tools_matter():
            self._tool_btn_down = down
            if down:
                self.engine.begin_tool_check()  # erst schauen, was in der Hand ist
                self._tool_kick.set()
        self.engine.set_mouse_held(button, down)

    # ─── Werkzeuge (Hotbar) ─────────────────────────────
    def _game_in_front(self) -> bool:
        """Irgendein anderes Fenster als der AutoClicker selbst (das Spiel)."""
        try:
            title = (self.backend.foreground_title() or "").lower()
        except Exception:
            return False
        return bool(title) and WINDOW_TITLE.lower() not in title

    def _in_game(self) -> bool:
        """Wirklich im Spiel: Spiel vorne und Mauszeiger versteckt. In Menues,
        Inventar und Chat zeigt Minecraft den Zeiger – dort zaehlt nichts."""
        try:
            return self._game_in_front() and not self.backend.cursor_visible()
        except Exception:
            return self._game_in_front()

    def _tools_matter(self) -> bool:
        return self.config.mode() in TOOL_MODES and bool(self._tool_masks)

    def _on_raw_input(self, kind: str, name: str, down: bool) -> None:
        """Tasten 1–9 / Mausrad im Spiel: gewaehlten Hotbar-Platz mitschreiben."""
        if not down or not (self.learning or self._tools_matter()) or not self._in_game():
            return
        before = self.slots.slot
        if kind == "k":
            self.slots.key(name)
        else:
            self.slots.wheel(name == "up")
        if self.slots.slot != before and self._tool_btn_down:
            self._tool_kick.set()  # waehrend gehalten wird gewechselt -> gleich nachschauen

    def _grab_hotbar(self):
        data = self.backend.grab_bottom(CAPTURE_GUI_H * MAX_SCALE)
        if not data:
            return None, None
        w, h, pixels, client_h = data
        shot = Shot(w, h, pixels, client_h)
        found = locate(shot, w, self.slots.slot)
        if found and found["sure"]:
            self.slots.sync(found["slot"])
        return shot, found

    def _check_tool(self) -> None:
        """Was ist gerade in der Hand? Nur ein erkanntes Werkzeug bremst den Klicker –
        leere Hand, Schwert oder Hotbar nicht zu sehen = normal schnell klicken."""
        index = -1
        try:
            shot, found = self._grab_hotbar() if self._game_in_front() else (None, None)
            self.hotbar_seen = bool(found and found["sure"])
            if found:
                index = best_match(item_sample(shot, found, found["slot"]), self._tool_masks)
        except Exception:
            index = -1
        self.tool_index = index
        self.engine.set_tool(index >= 0 and self._tools_matter())

    def _tool_loop(self) -> None:
        """Solange die Maustaste gedrueckt ist, regelmaessig nachschauen (Platz gewechselt?)."""
        while not self.quit_event.is_set():
            if not self._tool_kick.wait(0.5):
                continue
            self._tool_kick.clear()
            self._check_tool()
            while self._tool_btn_down and not self.quit_event.is_set():
                if self._tool_kick.wait(TOOL_RECHECK):
                    break
                self._check_tool()

    def _learn_mouse(self, down: bool) -> None:
        # Klick im Spiel (Druecken UND Loslassen dort, nicht im Pause-Menue) – im Kreativmodus
        # ist der Block sofort weg, deshalb reicht ein Klick
        if down:
            in_game = self._in_game()
            if not in_game and self._game_in_front():
                # Zeiger sichtbar = Menue. Falls ein Spiel den Zeiger nie versteckt,
                # nicht ewig haengen bleiben: der dritte Klick zaehlt trotzdem.
                self._learn_skipped += 1
                in_game = self._learn_skipped >= 3
            self._learn_press = in_game
        elif self._learn_press and self._game_in_front():
            self._learn_press = False
            threading.Thread(target=self._finish_learning, name="learn", daemon=True).start()

    def _finish_learning(self) -> None:
        """Block wurde abgebaut: Item in der Hand anschauen und als Werkzeug speichern."""
        time.sleep(0.05)
        try:
            shot, found = self._grab_hotbar()
        except Exception as e:
            shot, found = None, None
            self._log(f"Aufnahme-Fehler: {e!r}")
        item = item_sample(shot, found, found["slot"]) if found else None
        self._log_learn(shot, found, item)
        with self._lock:
            if not self.learning:
                return
            if item is None or item.empty:
                # Anlernen laeuft weiter – im Spiel hoert man, dass es nicht geklappt hat
                self.learn_error = "e_hotbar" if item is None else "e_tool_empty"
                self._notify(self.learn_error)
                self.backend.beep("learn_fail")
                return
            self.learning = False
            self.learn_error = ""
            self.config.learn_tool(item.mask_hex(), item.icon(), best_match(item, self._tool_masks, SAME_IOU))
            self._notify("n_tool_saved")
            self.backend.beep("learn_ok")
            self._apply()
            self._save_soon()

    def _log(self, line: str) -> None:
        """Kleines Protokoll fuer die Fehlersuche (hotbar-log.txt, nur die letzten Zeilen)."""
        path = os.path.join(self.folder, "hotbar-log.txt")
        try:
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.read().splitlines()[-60:]
            except OSError:
                lines = []
            lines.append(time.strftime("%Y-%m-%d %H:%M:%S ") + line)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

    def _log_learn(self, shot, found, item) -> None:
        try:
            title = self.backend.foreground_title()
        except Exception:
            title = "?"
        how = getattr(self.backend, "capture_info", "")
        if shot is None:
            self._log(f"Anlernen: keine Aufnahme ({how}) Fenster={title!r}")
            return
        self._save_debug_shot(shot)
        where = (f"Platz {found['slot']} Groesse {found['scale']} "
                 f"{'Rahmen erkannt' if found['sure'] else 'Rahmen NICHT erkannt (Tasten-Platz)'} "
                 f"({found['confidence']})") if found else "Hotbar nicht gefunden"
        what = f"Item {item.size} Pixel" if item else "-"
        self._log(f"Anlernen: {how} {shot.w}x{shot.client_h} Fenster={title!r} -> {where}, {what}")

    def _save_debug_shot(self, shot) -> None:
        """Letzte Aufnahme speichern – falls die Erkennung bei jemandem nicht klappt."""
        try:
            with open(os.path.join(self.folder, "hotbar-aufnahme.png"), "wb") as f:
                f.write(shot_png(shot))
        except Exception:
            pass

    def tools_action(self, body: dict):
        op = body.get("op")
        if op == "learn":
            self.engine.stop("manual")  # beim Anlernen nicht klicken
            self.learning = True
            self.learn_error = ""
            self._learn_press = False
            self._learn_skipped = 0
            self._learn_deadline = time.monotonic() + LEARN_TIMEOUT
        elif op == "cancel":
            self.learning = False
        elif op == "delete":
            index = body.get("index")
            if not isinstance(index, int) or not self.config.delete_tool(index):
                return {"error": "e_not_found"}
            self._save_soon()
        else:
            return {"error": "Unbekannte Aktion"}
        self._apply()
        return self.state()

    def _on_record(self, slot: str, text: str | None) -> None:
        with self._lock:
            target = self.recording
            self.recording = None
            if text:
                err = self.config.set_hotkey(None if target == NEW else target, text)
                if err:
                    self._notify(err)
                else:
                    self._notify("n_hotkey_saved")
                    self._save_soon()
            self._apply()

    def _on_engine_event(self, event: str) -> None:
        if self.config.data["general"]["sound"]:
            self.backend.beep(event)
        if event == "limit":
            self._notify("n_limit")
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
            "learning": self.learning,
            "learn_error": self.learn_error,
            "tool_index": self.tool_index,
            "hotbar": self.hotbar_seen,
            "notice": self.notice if self.notice and time.time() - self.notice["at"] < 6 else None,
            "update": self.update_state(),
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
                "tools": snap["tools"],
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
                on_top = self.config.data["general"]["always_on_top"]
                if self.native_window is not None:
                    try:
                        self.native_window.on_top = on_top
                    except Exception:
                        pass
                self.backend.set_topmost(WINDOW_TITLE, on_top)
            self._apply()
            self._save_soon()
            return self.state()
        if name == "preset":
            pid = str(body.get("id", ""))
            changed = pid != self.config.data["preset"]
            if not self.config.select(pid):
                return {"error": "Unbekannter Modus"}
            if changed:
                self.engine.stop("manual")  # Modus gewechselt -> Klicker aus
            self._apply()
            self._save_soon()
            return self.state()
        if name == "hotkeys":
            return self.hotkeys(body)
        if name == "tools":
            return self.tools_action(body)
        if name == "update":
            return self.update_action(str(body.get("op", "")))
        if name == "bye":
            if client == "desktop":
                self._bye_at = time.monotonic()
            return {"ok": True}
        return None

    # ─── Updates ────────────────────────────────────────
    def update_state(self) -> dict | None:
        u = self.updater
        if u.status in ("downloading", "installing", "error"):
            return {"version": (u.available or {}).get("version", ""), "status": u.status,
                    "progress": round(u.progress, 2), "error": u.error, "can_install": self.can_self_update}
        info = u.available
        if not info:
            return None
        g = self.config.data["general"]
        if g["update_skip"] == info["version"] or time.time() < g["update_snooze_until"]:
            return None
        return {"version": info["version"], "status": "available", "progress": 0,
                "error": "", "can_install": self.can_self_update}

    def update_action(self, op: str):
        info = self.updater.available
        if op == "check":
            self.updater.check()
        elif not info:
            return {"error": "Kein Update verfügbar"}
        elif op == "later":
            self.config.update({"general": {"update_snooze_until": time.time() + SNOOZE_SECONDS}})
            self._save_soon()
        elif op == "skip":
            self.config.update({"general": {"update_skip": info["version"]}})
            self._save_soon()
        elif op == "install":
            if not self.can_self_update:  # aus dem Quellcode gestartet -> Download-Seite oeffnen
                webbrowser.open(info["page"])
                return self.state()
            self.engine.stop("manual")
            self.updater.install(self._before_update, self._after_update)
        else:
            return {"error": "Unbekannte Aktion"}
        return self.state()

    def _before_update(self) -> None:
        self._store_stats()
        self.config.save()
        self.backend.release_instance()

    def _after_update(self) -> None:
        # Der Installer laeuft – Programm beenden, damit er die Dateien ersetzen kann
        self.quit_event.set()

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
                return {"error": "e_not_found"}
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
    parser.add_argument("--selftest", metavar="DATEI", help=argparse.SUPPRESS)  # Build-Test: Fenster öffnet?
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Umlaute dürfen den Start nie abbrechen
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass

    root, web_dir, data_dir = _paths()
    app = App(data_dir, web_dir, demo=args.demo, keep_alive=args.no_window)
    app.icon_path = os.path.join(os.path.dirname(web_dir), "assets", "icon.ico")
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

    if args.selftest:
        threading.Thread(target=_selftest, args=(app, args.selftest), daemon=True).start()

    if not args.no_window:
        url = app.local_url() + "&client=desktop"
        native_ok = False
        if not args.browser:
            def ready(win):
                app.native_window = win
                app.window_kind = "native"
                # Programm wird beendet (z. B. fuer ein Update) -> Fenster schliessen
                threading.Thread(target=_close_on_quit, args=(app, win), daemon=True).start()
            native_ok = run_native_window(url, WINDOW_TITLE, app.config.data["general"]["always_on_top"],
                                          app.icon_path, ready)
            if native_ok:
                app.quit_event.set()  # Fenster geschlossen = Programm beenden
            else:
                app.native_window, app.window_kind = None, ""
        if not native_ok:
            app.window_kind = "browser"
            proc = open_app_window(url, data_dir, use_browser=args.browser)
            if proc is not None:
                threading.Thread(target=_watch_window, args=(app, proc), daemon=True).start()

    try:
        while not app.quit_event.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    app.shutdown()
    return 0


def _close_on_quit(app: App, win) -> None:
    app.quit_event.wait()
    try:
        win.destroy()
    except Exception:
        pass


def _selftest(app: App, path: str) -> None:
    """Fuer den automatischen Build-Test: laedt die Oberflaeche im Fenster?"""
    end = time.monotonic() + 40
    while time.monotonic() < end and not app._last_desktop_poll:
        time.sleep(0.2)
    result = f"{app.window_kind or 'none'} {'ok' if app._last_desktop_poll else 'timeout'}"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(result)
    finally:
        app.quit_event.set()


def _watch_window(app: App, proc) -> None:
    started = time.monotonic()
    proc.wait()
    # Sehr kurze Laufzeit = Browser hat an ein anderes Fenster uebergeben -> ignorieren
    if time.monotonic() - started > 5 and not app.keep_alive:
        app.quit_event.set()


if __name__ == "__main__":
    sys.exit(main())
