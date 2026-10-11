"""Klick-Engine: Zustandsautomat + praezises Timing + Live-Statistik.

Zustaende (fuer die Oberflaeche):
  idle       – aus
  countdown  – Start-Countdown laeuft
  ready      – bereit, wartet auf die gehaltene Maus-/Tastaturtaste
  clicking   – klickt gerade (bzw. haelt die Taste beim Dauerdruecken)
  paused     – an, aber pausiert (falsches Fenster, Inventar offen, ...)

Modi:
  toggle      – Hotkey/Button schaltet an und aus
  hold_mouse  – an + Maustaste gedrueckt halten = Autoklick (klassisch fuer PvP)
  hold_key    – klickt, solange der Hotkey gehalten wird

Timing: absolute Zeitplanung (kein Aufsummieren von Verzoegerungen),
grob schlafen und nur die letzten ~2 ms genau warten. Dadurch stimmen auch
hohe CPS, ohne dauerhaft einen CPU-Kern zu belegen.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from . import APP_NAME

MODES = ("toggle", "hold_mouse", "hold_key")
BUTTONS = ("left", "right", "middle")
ACTIONS = ("click", "hold")


@dataclass
class ClickSettings:
    button: str = "left"
    mode: str = "toggle"
    action: str = "click"
    cps_min: float = 10.0
    cps_max: float = 10.0
    hold_ms: float = 0.0
    limit_seconds: float = 0.0
    limit_clicks: int = 0
    start_delay: float = 0.0


@dataclass
class SmartSettings:
    window_lock: bool = False
    window_match: list = field(default_factory=lambda: ["Minecraft"])
    pause_in_menus: bool = False


class ClickEngine:
    UI_MIN_DELAY = 3.0  # Start per Button/Handy: Zeit, um die Maus ins Spiel zu bewegen

    def __init__(self, backend, clock=time.perf_counter):
        self.backend = backend
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._quit = False
        self.cfg = ClickSettings()
        self.smart = SmartSettings()
        self.on_event = None  # callback(name) – "start", "stop", "limit", "tick"

        self._armed = False
        self._countdown_end: float | None = None
        self._last_tick = 0
        self._run_start: float | None = None
        self._run_clicks = 0
        self._mouse_held: set[str] = set()
        self._key_held = False
        self._holding_button: str | None = None
        self._state = "idle"
        self._reason = ""
        self._stop_reason = ""

        self.total_clicks = 0       # diese Session
        self.lifetime_base = 0      # alle frueheren Sessions (aus der Config)
        self.best_cps = 0.0
        self.cps_live = 0.0
        self._samples: deque = deque(maxlen=5)
        self.history: deque = deque([0.0] * 120, maxlen=120)  # 30 s bei 4 Hz

        self._fg_cache = ("", -1.0)
        self._cap_cache = (None, -1.0)

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
            self._countdown_end = None
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(1.0)
        self._release_hold()
        self.backend.set_timer_resolution(False)

    def configure(self, cfg: ClickSettings, smart: SmartSettings) -> None:
        with self._lock:
            self.cfg = cfg
            self.smart = smart
            if cfg.mode == "hold_key":
                # In diesem Modus gibt es kein "an/aus" – nur Taste halten
                self._armed = False
                self._countdown_end = None
                self._run_start = None
        self._wake.set()

    # ─── Steuerung ────────────────────────────────────────
    @property
    def armed(self) -> bool:
        return self._armed

    def toggle(self, source: str = "ui") -> None:
        with self._lock:
            on = self._armed or self._countdown_end is not None
        if on:
            self.stop("manual")
        else:
            self.start(source)

    def start(self, source: str = "ui") -> None:
        events = []
        with self._lock:
            if (self._quit or self._armed or self._countdown_end is not None
                    or self.cfg.mode == "hold_key"):
                return
            delay = max(0.0, self.cfg.start_delay)
            if source in ("ui", "remote"):
                delay = max(delay, self.UI_MIN_DELAY)
            self._stop_reason = ""
            if delay > 0:
                self._countdown_end = self._clock() + delay
                self._last_tick = int(delay + 0.999)
                events.append("tick")
            else:
                self._arm_now()
                events.append("start")
        self._wake.set()
        self._emit(events)

    def stop(self, reason: str = "manual") -> None:
        with self._lock:
            was_on = self._armed or self._countdown_end is not None
            self._armed = False
            self._countdown_end = None
            self._run_start = None
            if was_on:
                self._stop_reason = reason
        self._wake.set()
        if was_on:
            self._emit(["limit" if reason == "limit" else "stop"])

    def set_mouse_held(self, button: str, held: bool) -> None:
        with self._lock:
            if held:
                self._mouse_held.add(button)
            else:
                self._mouse_held.discard(button)
        self._wake.set()

    def set_key_held(self, held: bool) -> None:
        with self._lock:
            self._key_held = held
        self._wake.set()

    def reset_stats(self) -> None:
        with self._lock:
            self.lifetime_base += self.total_clicks
            self.total_clicks = 0
            self._run_clicks = 0
            self.best_cps = 0.0
            self.history.extend([0.0] * self.history.maxlen)
            self._samples.clear()
            if self._run_start is not None:
                self._run_start = self._clock()

    def lifetime_clicks(self) -> int:
        return self.lifetime_base + self.total_clicks

    # ─── Status fuer die UI ───────────────────────────────
    def status(self) -> dict:
        now = self._clock()
        with self._lock:
            c = self.cfg
            cd = max(0.0, self._countdown_end - now) if self._countdown_end is not None else None
            run_time = (now - self._run_start) if self._run_start is not None else 0.0
            progress = None
            if self._armed and c.limit_clicks > 0:
                progress = min(1.0, self._run_clicks / c.limit_clicks)
            if self._armed and c.limit_seconds > 0:
                p = min(1.0, run_time / c.limit_seconds)
                progress = p if progress is None else max(progress, p)
            return {
                "state": self._state,
                "reason": self._reason,
                "stop_reason": self._stop_reason,
                "armed": self._armed,
                "countdown": cd,
                "run_time": round(run_time, 2),
                "run_clicks": self._run_clicks,
                "session_clicks": self.total_clicks,
                "lifetime_clicks": self.lifetime_clicks(),
                "cps": round(self.cps_live, 1),
                "best_cps": round(self.best_cps, 1),
                "history": [round(v, 1) for v in self.history],
                "limit_progress": progress,
                "holding": self._holding_button is not None,
            }

    # ─── intern ───────────────────────────────────────────
    def _emit(self, events) -> None:
        cb = self.on_event
        if not cb:
            return
        for ev in events:
            try:
                cb(ev)
            except Exception:
                pass

    def _arm_now(self) -> None:
        self._armed = True
        self._countdown_end = None
        self._run_start = self._clock()
        self._run_clicks = 0

    def _foreground(self, now: float) -> str:
        title, ts = self._fg_cache
        if now - ts > 0.05 or ts < 0:
            try:
                title = self.backend.foreground_title() or ""
            except Exception:
                title = ""
            self._fg_cache = (title, now)
        return title

    def _captured(self, now: float):
        val, ts = self._cap_cache
        if now - ts > 0.05 or ts < 0:
            try:
                val = self.backend.mouse_captured()
            except Exception:
                val = None
            self._cap_cache = (val, now)
        return val

    def _evaluate(self, now: float) -> tuple[str, str]:
        """-> (state, reason). Nur 'clicking' bedeutet: jetzt klicken."""
        c, s = self.cfg, self.smart
        if self._countdown_end is not None:
            return "countdown", ""
        if c.mode == "hold_key":
            if not self._key_held:
                return "ready", "key"
        elif not self._armed:
            return "idle", ""
        elif c.mode == "hold_mouse" and c.button not in self._mouse_held:
            return "ready", "mouse"
        low = self._foreground(now).lower()
        if s.window_lock:
            if not any(m.strip().lower() in low for m in s.window_match if m.strip()):
                return "paused", "window"
        elif APP_NAME.lower() in low:
            return "paused", "self"  # nie ins eigene Fenster klicken
        if s.pause_in_menus and self._captured(now) is False:
            return "paused", "menu"
        return "clicking", ""

    def _limit_reached(self, now: float) -> bool:
        c = self.cfg
        if not self._armed:
            return False
        if c.limit_clicks > 0 and self._run_clicks >= c.limit_clicks:
            return True
        return (c.limit_seconds > 0 and self._run_start is not None
                and now - self._run_start >= c.limit_seconds)

    def _next_interval(self, cfg: ClickSettings) -> float:
        lo, hi = sorted((max(0.1, cfg.cps_min), max(0.1, cfg.cps_max)))
        cps = lo if hi - lo < 1e-9 else random.uniform(lo, hi)
        return 1.0 / cps

    def _release_hold(self) -> None:
        btn = self._holding_button
        if btn:
            self._holding_button = None
            try:
                self.backend.release(btn)
            except Exception:
                pass

    def _wait(self, seconds: float) -> None:
        if seconds > 0 and self._wake.wait(seconds):
            self._wake.clear()

    def _loop(self) -> None:
        next_t: float | None = None
        timer_high = False
        while not self._quit:
            now = self._clock()
            events = []
            with self._lock:
                if self._countdown_end is not None:
                    left = self._countdown_end - now
                    if left <= 0:
                        self._arm_now()
                        events.append("start")
                    else:
                        tick = int(left + 0.999)
                        if tick < self._last_tick:
                            self._last_tick = tick
                            events.append("tick")
                limit_hit = self._limit_reached(now)
                if not limit_hit:
                    state, reason = self._evaluate(now)
                    self._state, self._reason = state, reason
                cfg = self.cfg
            self._emit(events)
            if limit_hit:
                self.stop("limit")
                continue

            want_timer = state == "clicking"
            if want_timer != timer_high:
                self.backend.set_timer_resolution(want_timer)
                timer_high = want_timer

            if state != "clicking":
                self._release_hold()
                next_t = None
                self._wait({"countdown": 0.02, "paused": 0.02, "ready": 0.05}.get(state, 0.25))
                continue

            # Dauerdruecken (nur im Umschalt-Modus)
            if cfg.action == "hold" and cfg.mode == "toggle":
                if self._holding_button != cfg.button:
                    self._release_hold()
                    self.backend.press(cfg.button)
                    self._holding_button = cfg.button
                self._wait(0.02)
                continue
            self._release_hold()

            if next_t is None:
                # Bei "Maus halten" hat der echte Klick gerade schon ausgeloest
                next_t = now + (self._next_interval(cfg) if cfg.mode == "hold_mouse" else 0.0)
            remaining = next_t - now
            if remaining > 0.003:
                self._wait(remaining - 0.002)
                continue  # neu bewerten – Zustand kann sich geaendert haben
            while self._clock() < next_t:
                time.sleep(0)

            interval = self._next_interval(cfg)
            hold_s = min(cfg.hold_ms / 1000.0, interval * 0.6)
            try:
                self.backend.click(cfg.button, hold_s)
            except Exception:
                pass
            with self._lock:
                self.total_clicks += 1
                self._run_clicks += 1

            next_t += interval
            after = self._clock()
            if next_t < after - 0.010:  # weit hinterher -> kein Nachhol-Burst
                next_t = after
        self._release_hold()

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
                self.history.append(cps)
                if cps > self.best_cps:
                    self.best_cps = cps
            time.sleep(0.25)
