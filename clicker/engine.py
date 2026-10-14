"""Klick-Engine: an/aus, praezises Timing und Live-CPS.

Zustaende (fuer die Oberflaeche):
  idle      – aus
  countdown – Start-Countdown laeuft (nur wenn in den Einstellungen eingestellt)
  ready     – an, wartet auf echte Klicks (Minecraft PvP / CPS-Boost)
  clicking  – klickt gerade
  paused    – an, aber pausiert (anderes Fenster vorne / eigenes Fenster)

Modi:
  toggle      – an = klickt sofort mit dem eingestellten Tempo
  hold_mouse  – an + Maustaste gedrueckt halten = schnelle Klicks
  boost       – an + jeder echte Klick bekommt Extra-Klicks (x2 / x3)

Werkzeug (nur hold_mouse / boost): Ist ein angelerntes Werkzeug in der Hand
(siehe hotbar.py), wird nicht geklickt – die Maustaste bleibt normal gedrueckt,
damit man Bloecke abbauen kann.

Aktion (nur bei toggle):
  click – klicken im eingestellten Tempo
  hold  – Maustaste dauerhaft gedrueckt halten (z. B. Baeume/Steine abbauen)

Timing: absolute Zeitplanung (kein Aufsummieren von Verzoegerungen),
grob schlafen und nur die letzten ~2 ms genau warten.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from . import WINDOW_TITLE

MODES = ("toggle", "hold_mouse", "boost")
ACTIONS = ("click", "hold")
BUTTONS = ("left", "right", "middle")
MAX_PENDING_BOOST = 6  # nie mehr Extra-Klicks auf einmal nachholen


@dataclass
class ClickSettings:
    button: str = "left"
    mode: str = "toggle"
    cps_min: float = 10.0
    cps_max: float = 10.0
    boost: int = 2
    action: str = "click"
    limit_seconds: float = 0.0
    start_delay: float = 0.0


@dataclass
class SmartSettings:
    window_lock: bool = False
    window_match: list = field(default_factory=lambda: ["Minecraft"])
    # In Menues nicht klicken: in diesen Spielfenstern heisst "Mauszeiger sichtbar" =
    # Inventar, Truhe, Chat oder Pause-Menue offen (im Spiel selbst ist er versteckt)
    menu_pause: bool = False
    menu_windows: list = field(default_factory=list)


class ClickEngine:
    def __init__(self, backend, clock=time.perf_counter):
        self.backend = backend
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._quit = False
        self.cfg = ClickSettings()
        self.smart = SmartSettings()
        self.on_event = None  # callback(name): "start", "stop", "limit"

        self._armed = False
        self._countdown_end: float | None = None
        self._run_start: float | None = None
        self._mouse_held: set[str] = set()
        self._boost_owed = 0                 # Extra-Klicks, die noch faellig sind
        self._boost_due: float | None = None  # Zeitpunkt des naechsten Extra-Klicks
        self._holding: str | None = None   # Taste, die gerade dauerhaft gedrueckt wird
        self._tool = False                  # Werkzeug in der Hand -> nicht klicken
        self._tool_check_until = 0.0        # kurz warten, bis die Hotbar angeschaut ist
        self._suspended = False             # an, aber gerade angehalten (Werkzeug anlernen)
        self._state = "idle"
        self._reason = ""
        self._stop_reason = ""

        self.total_clicks = 0       # diese Sitzung
        self.lifetime_base = 0      # alle frueheren Sitzungen (aus der Config)
        self.best_cps = 0.0
        self.cps_live = 0.0
        self._samples: deque = deque(maxlen=5)
        self._fg_cache = ("", -1.0)
        self._cursor_cache = (False, -1.0)

        self._thread = threading.Thread(target=self._loop, name="click-engine", daemon=True)
        self._stats = threading.Thread(target=self._stats_loop, name="stats", daemon=True)

    # ─── Lebenszyklus ─────────────────────────────────────
    def start_threads(self) -> None:
        self._thread.start()
        self._stats.start()

    def shutdown(self) -> None:
        with self._lock:
            self._quit = True
            self._armed = False
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(1.0)
        self._release_hold()
        self.backend.set_timer_resolution(False)

    def configure(self, cfg: ClickSettings, smart: SmartSettings) -> None:
        with self._lock:
            if cfg.mode != self.cfg.mode or cfg.button != self.cfg.button:
                self._clear_boost()
            self.cfg = cfg
            self.smart = smart
        self._wake.set()

    # ─── Steuerung ────────────────────────────────────────
    @property
    def armed(self) -> bool:
        return self._armed

    def toggle(self, reason: str = "manual") -> None:
        if self._armed or self._countdown_end is not None:
            self.stop(reason)
        else:
            self.start()

    def suspend(self, on: bool) -> None:
        """Kurz nicht klicken, aber AN bleiben (z. B. waehrend "Werkzeug anlernen")."""
        with self._lock:
            self._suspended = on
        self._wake.set()

    def start(self) -> None:
        """An – sofort, oder nach dem eingestellten Countdown."""
        with self._lock:
            if self._quit or self._armed or self._countdown_end is not None:
                return
            self._stop_reason = ""
            if self.cfg.start_delay > 0:
                self._countdown_end = self._clock() + self.cfg.start_delay
                event = "countdown"
            else:
                self._arm()
                event = "start"
        self._wake.set()
        self._emit(event)

    def _arm(self) -> None:
        self._armed = True
        self._countdown_end = None
        self._run_start = self._clock()
        self._clear_boost()

    def stop(self, reason: str = "manual") -> None:
        with self._lock:
            was_on = self._armed or self._countdown_end is not None
            self._armed = False
            self._countdown_end = None
            self._run_start = None
            self._clear_boost()
            if was_on:
                self._stop_reason = reason
        self._wake.set()
        if was_on:
            self._emit("limit" if reason == "limit" else "stop")

    def set_mouse_held(self, button: str, held: bool) -> None:
        """Echte (physische) Maustaste gedrueckt/losgelassen."""
        with self._lock:
            was = button in self._mouse_held
            if held:
                self._mouse_held.add(button)
            else:
                self._mouse_held.discard(button)
            c = self.cfg
            if self._armed and button == c.button and c.mode in ("hold_mouse", "boost"):
                if held and not was:
                    self.total_clicks += 1  # der echte Klick zaehlt in der CPS-Anzeige mit
                elif was and not held and c.mode == "boost" and not self._tool:
                    # Extra-Klicks nach dem Loslassen. Was beim letzten Klick nicht mehr
                    # geschafft wurde (zu schnell wieder gedrueckt), wird jetzt nachgeholt.
                    self._boost_owed = min(MAX_PENDING_BOOST, self._boost_owed + max(1, c.boost) - 1)
                    self._boost_due = self._clock() + random.uniform(0.012, 0.024)
        self._wake.set()

    def begin_tool_check(self, seconds: float = 0.12) -> None:
        """Maustaste gedrueckt: kurz nicht klicken, bis feststeht, was in der Hand ist."""
        with self._lock:
            self._tool_check_until = self._clock() + seconds

    def set_tool(self, active: bool) -> None:
        """Ergebnis der Hotbar-Pruefung: Werkzeug in der Hand oder nicht."""
        press = None
        with self._lock:
            self._tool_check_until = 0.0
            if active == self._tool:
                self._wake.set()
                return
            self._tool = active
            c = self.cfg
            if active:
                self._clear_boost()
                # Waehrend gehalten wurde gewechselt: unser letzter Klick hat die Taste im
                # Spiel losgelassen -> wieder druecken, damit sofort abgebaut wird.
                if self._armed and c.mode == "hold_mouse" and c.button in self._mouse_held:
                    press = c.button
        if press:
            try:
                self.backend.press(press)
            except Exception:
                pass
        self._wake.set()

    @property
    def tool(self) -> bool:
        return self._tool

    def reset_stats(self) -> None:
        with self._lock:
            self.lifetime_base += self.total_clicks
            self.total_clicks = 0
            self.best_cps = 0.0
            self._samples.clear()
            if self._run_start is not None:
                self._run_start = self._clock()

    def lifetime_clicks(self) -> int:
        return self.lifetime_base + self.total_clicks

    # ─── Status fuer die Oberflaeche ──────────────────────
    def status(self) -> dict:
        now = self._clock()
        with self._lock:
            run_time = (now - self._run_start) if self._run_start is not None else 0.0
            return {
                "state": self._state,
                "reason": self._reason,
                "stop_reason": self._stop_reason,
                "armed": self._armed,
                "holding": self._holding is not None,
                "tool": self._tool,
                "countdown": (max(0.0, self._countdown_end - now)
                              if self._countdown_end is not None else None),
                "run_time": round(run_time, 2),
                "session_clicks": self.total_clicks,
                "lifetime_clicks": self.lifetime_clicks(),
                "cps": round(self.cps_live, 1),
                "best_cps": round(self.best_cps, 1),
            }

    # ─── intern ───────────────────────────────────────────
    def _emit(self, event: str) -> None:
        cb = self.on_event
        if cb:
            try:
                cb(event)
            except Exception:
                pass

    def _clear_boost(self) -> None:
        self._boost_owed = 0
        self._boost_due = None

    def _foreground(self, now: float) -> str:
        title, ts = self._fg_cache
        if now - ts > 0.05 or ts < 0:
            try:
                title = self.backend.foreground_title() or ""
            except Exception:
                title = ""
            self._fg_cache = (title, now)
        return title

    def _cursor_visible(self, now: float) -> bool:
        shown, ts = self._cursor_cache
        if now - ts > 0.05 or ts < 0:
            try:
                shown = bool(self.backend.cursor_visible())
            except Exception:
                shown = False
            self._cursor_cache = (shown, now)
        return shown

    def _evaluate(self, now: float) -> tuple[str, str]:
        """-> (state, reason). Nur 'clicking' bedeutet: jetzt klicken."""
        c, s = self.cfg, self.smart
        if self._countdown_end is not None:
            return "countdown", ""
        if not self._armed:
            return "idle", ""
        if self._suspended:
            return "paused", "learn"
        if c.mode in ("hold_mouse", "boost"):
            if self._tool:
                return "ready", "tool"  # Werkzeug: Maustaste normal halten, nicht klicken
            if now < self._tool_check_until:
                return "ready", "check"
        if c.mode == "hold_mouse" and c.button not in self._mouse_held:
            return "ready", "mouse"
        if c.mode == "boost" and (not self._boost_owed or c.button in self._mouse_held):
            return "ready", "boost"  # beim Halten nie dazwischenklicken
        low = self._foreground(now).lower()
        if s.window_lock:
            if not any(m.strip().lower() in low for m in s.window_match if m.strip()):
                return "paused", "window"
        elif WINDOW_TITLE.lower() in low:
            return "paused", "self"  # nie ins eigene Fenster klicken
        if (s.menu_pause and any(m.strip().lower() in low for m in s.menu_windows if m.strip())
                and self._cursor_visible(now)):
            self._clear_boost()  # Extra-Klicks nicht nach dem Schliessen nachholen
            return "paused", "menu"
        return "clicking", ""

    def _next_interval(self, cfg: ClickSettings) -> float:
        lo, hi = sorted((max(0.1, cfg.cps_min), max(0.1, cfg.cps_max)))
        cps = lo if hi - lo < 1e-9 else random.uniform(lo, hi)
        return 1.0 / cps

    def _wait(self, seconds: float) -> None:
        if seconds > 0 and self._wake.wait(seconds):
            self._wake.clear()

    def _sleep_until(self, target: float) -> bool:
        """Bis target warten. False = frueher aufgeweckt (Zustand neu pruefen)."""
        remaining = target - self._clock()
        if remaining > 0.003:
            self._wait(remaining - 0.002)
            return False
        while self._clock() < target:
            time.sleep(0)
        return True

    def _release_hold(self) -> None:
        """Gehaltene Taste loslassen (beim Stoppen, Pausieren, Moduswechsel)."""
        btn = self._holding
        if btn:
            self._holding = None
            try:
                self.backend.release(btn)
            except Exception:
                pass

    def _click(self, button: str) -> None:
        try:
            self.backend.click(button)
        except Exception:
            pass
        with self._lock:
            self.total_clicks += 1

    def _loop(self) -> None:
        next_t: float | None = None
        timer_high = False
        while not self._quit:
            now = self._clock()
            started = False
            with self._lock:
                if self._countdown_end is not None and now >= self._countdown_end:
                    self._arm()
                    started = True
                c = self.cfg
                limit_hit = (self._armed and c.limit_seconds > 0 and self._run_start is not None
                             and now - self._run_start >= c.limit_seconds)
                if not limit_hit:
                    self._state, self._reason = self._evaluate(now)
                state, cfg = self._state, self.cfg
            if started:
                self._emit("start")
            if limit_hit:
                self.stop("limit")
                continue

            want_timer = state in ("clicking", "ready")
            if want_timer != timer_high:
                self.backend.set_timer_resolution(want_timer)
                timer_high = want_timer

            if state != "clicking":
                next_t = None
                self._release_hold()
                self._wait(0.02 if state in ("paused", "countdown") else 0.05 if state == "ready" else 0.25)
                continue

            # Gedrueckt halten (AFK: Baeume, Steine, Angeln ...)
            if cfg.mode == "toggle" and cfg.action == "hold":
                next_t = None
                if self._holding != cfg.button:
                    self._release_hold()
                    try:
                        self.backend.press(cfg.button)
                        self._holding = cfg.button
                    except Exception:
                        pass
                self._wait(0.05)
                continue
            self._release_hold()

            if cfg.mode == "boost":
                next_t = None
                with self._lock:
                    due = self._boost_due if self._boost_due is not None else now
                if not self._sleep_until(due):
                    continue
                with self._lock:
                    # waehrend des Wartens wieder gedrueckt? Dann nach dem Loslassen nachholen
                    if not self._boost_owed or cfg.button in self._mouse_held or not self._armed:
                        continue
                    self._boost_owed -= 1
                    self._boost_due = self._clock() + random.uniform(0.028, 0.045)
                self._click(cfg.button)
                continue

            if next_t is None:
                # Bei "Maus halten" hat der echte Klick gerade schon ausgeloest
                next_t = now + (self._next_interval(cfg) if cfg.mode == "hold_mouse" else 0.0)
            if not self._sleep_until(next_t):
                continue  # neu bewerten – Zustand kann sich geaendert haben
            self._click(cfg.button)
            next_t += self._next_interval(cfg)
            after = self._clock()
            if next_t < after - 0.010:  # weit hinterher -> kein Nachhol-Burst
                next_t = after

    def _stats_loop(self) -> None:
        while not self._quit:
            with self._lock:
                now = self._clock()
                self._samples.append((now, self.total_clicks))
                cps = 0.0
                if len(self._samples) >= 2:
                    (t0, c0), (t1, c1) = self._samples[0], self._samples[-1]
                    if t1 > t0 and c1 >= c0:
                        cps = (c1 - c0) / (t1 - t0)
                self.cps_live = cps
                if cps > self.best_cps:
                    self.best_cps = cps
            time.sleep(0.25)
