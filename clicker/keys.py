"""Tasten-Namen, Hotkey-Format und Hotkey-Erkennung (plattformunabhaengig).

Ein Hotkey ist ein String wie "f6", "ctrl+shift+r" oder "mouse4".
Der Hook (Windows) liefert rohe Ereignisse (Name + gedrueckt/losgelassen),
HotkeyMatcher entscheidet daraus, welcher Hotkey ausgeloest wurde.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

MODIFIERS = ("ctrl", "shift", "alt", "win")

# Windows Virtual-Key-Codes -> Name
VK_NAMES: dict[int, str] = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x13: "pause",
    0x14: "capslock", 0x1B: "esc", 0x20: "space",
    0x21: "pageup", 0x22: "pagedown", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "printscreen", 0x2D: "insert", 0x2E: "delete",
    0x5D: "menu",
    0x6A: "num_mul", 0x6B: "num_add", 0x6D: "num_sub", 0x6E: "num_dec", 0x6F: "num_div",
    0x90: "numlock", 0x91: "scrolllock",
    0xBA: "semicolon", 0xBB: "plus", 0xBC: "comma", 0xBD: "minus", 0xBE: "period",
    0xBF: "slash", 0xC0: "backtick", 0xDB: "bracketleft", 0xDC: "backslash",
    0xDD: "bracketright", 0xDE: "quote", 0xE2: "oem102",
    # Modifier (links/rechts zusammengefasst)
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
}
for _i in range(10):
    VK_NAMES[0x30 + _i] = str(_i)
    VK_NAMES[0x60 + _i] = f"num{_i}"
for _i in range(26):
    VK_NAMES[0x41 + _i] = chr(ord("a") + _i)
for _i in range(24):
    VK_NAMES[0x70 + _i] = f"f{_i + 1}"

MOUSE_HOTKEYS = ("mouse3", "mouse4", "mouse5")  # Mitte, Seitentaste hinten, vorne
ALL_KEY_NAMES = frozenset(VK_NAMES.values()) | frozenset(MOUSE_HOTKEYS)


def vk_to_name(vk: int) -> str:
    return VK_NAMES.get(vk, f"vk{vk:02x}")


def is_valid_key(name: str) -> bool:
    if name in ALL_KEY_NAMES:
        return True
    if name.startswith("vk") and len(name) in (4, 5):
        try:
            int(name[2:], 16)
            return True
        except ValueError:
            return False
    return False


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset
    key: str

    def __str__(self) -> str:
        parts = [m for m in MODIFIERS if m in self.mods]
        parts.append(self.key)
        return "+".join(parts)


def parse_hotkey(text: str) -> Hotkey | None:
    """'Ctrl + Shift + F6' -> Hotkey(mods={ctrl, shift}, key='f6'). Ungueltig -> None."""
    if not text:
        return None
    parts = [p.strip().lower() for p in str(text).split("+")]
    if any(not p for p in parts):
        return None
    *mods, key = parts
    if not is_valid_key(key):
        return None
    if any(m not in MODIFIERS for m in mods):
        return None
    mods_set = frozenset(mods) - {key}
    return Hotkey(mods_set, key)


def normalize_hotkey(text: str) -> str:
    hk = parse_hotkey(text)
    return str(hk) if hk else ""


class HotkeyMatcher:
    """Verarbeitet rohe Tasten-/Maus-Ereignisse.

    - Erkennt Hotkeys (Modifier-tolerant: "f6" loest auch aus, wenn gerade
      Strg zum Sprinten gehalten wird).
    - Filtert Auto-Repeat (gehaltene Taste loest nur einmal aus).
    - Kann die naechste Taste "aufnehmen" (Hotkey-Recorder).
    - Meldet physische Maustasten (fuer den "Maus halten"-Modus).
    """

    STALE_AFTER = 1.5  # s ohne Wiederholung -> verpasstes Loslassen annehmen

    def __init__(self, on_hotkey, on_mouse=None, on_record=None, clock=time.monotonic):
        self._on_hotkey = on_hotkey      # (slot, down: bool)
        self._on_mouse = on_mouse        # (button 'left'|'right'|'middle', down)
        self._on_record = on_record      # (slot, hotkey_str | None)
        self._clock = clock
        self._lock = threading.RLock()
        self._bindings: dict[str, Hotkey] = {}
        self._pressed: dict[str, float] = {}   # name -> letzter Down-Zeitpunkt
        self._active: dict[str, str] = {}      # slot -> key, solange gehalten
        self._recording: str | None = None
        self._rec_mod_alone: str | None = None

    # ---------- Konfiguration ----------
    def set_bindings(self, bindings: dict[str, str]) -> None:
        with self._lock:
            parsed = {}
            for slot, text in bindings.items():
                hk = parse_hotkey(text)
                if hk:
                    parsed[slot] = hk
            self._bindings = parsed
            self._active.clear()

    def wants_mouse_buttons(self) -> bool:
        with self._lock:
            return self._recording is not None or any(
                hk.key in MOUSE_HOTKEYS for hk in self._bindings.values())

    def start_recording(self, slot: str) -> None:
        with self._lock:
            self._recording = slot
            self._rec_mod_alone = None

    def stop_recording(self) -> None:
        """Aufnahme beenden, ohne Rueckmeldung (Taste kam von woanders)."""
        with self._lock:
            self._recording = None

    def cancel_recording(self) -> None:
        with self._lock:
            slot = self._recording
            self._recording = None
        if slot and self._on_record:
            self._on_record(slot, None)

    @property
    def recording(self) -> str | None:
        return self._recording

    def held_modifiers(self) -> frozenset:
        with self._lock:
            return frozenset(n for n in self._pressed if n in MODIFIERS)

    # ---------- Ereignisse ----------
    def key_event(self, name: str, down: bool) -> None:
        now = self._clock()
        fire: list[tuple[str, bool]] = []
        record: tuple[str, str | None] | None = None
        with self._lock:
            if down:
                last = self._pressed.get(name)
                self._pressed[name] = now
                if last is not None and now - last < self.STALE_AFTER:
                    return  # Auto-Repeat
                mods = frozenset(n for n in self._pressed if n in MODIFIERS and n != name)
                if self._recording:
                    if name == "esc":
                        record = (self._recording, None)
                        self._recording = None
                    elif name in MODIFIERS:
                        self._rec_mod_alone = name
                    else:
                        record = (self._recording, str(Hotkey(mods, name)))
                        self._recording = None
                else:
                    fire = self._match_down(name, mods)
            else:
                self._pressed.pop(name, None)
                if self._recording and name in MODIFIERS and self._rec_mod_alone == name:
                    # Modifier allein gedrueckt und losgelassen -> z. B. "shift" als Hotkey
                    mods = frozenset(n for n in self._pressed if n in MODIFIERS)
                    record = (self._recording, str(Hotkey(mods, name)))
                    self._recording = None
                elif not self._recording:
                    fire = self._match_up(name)
        self._dispatch(fire, record)

    def mouse_event(self, button: str, down: bool) -> None:
        """button: 'left' | 'right' | 'middle' | 'x1' | 'x2' (nur physische Ereignisse)."""
        name = {"middle": "mouse3", "x1": "mouse4", "x2": "mouse5"}.get(button)
        if button in ("left", "right", "middle") and self._on_mouse:
            self._on_mouse(button, down)
        if name is None:
            return
        fire: list[tuple[str, bool]] = []
        record = None
        with self._lock:
            if down:
                if self._recording:
                    mods = frozenset(n for n in self._pressed if n in MODIFIERS)
                    record = (self._recording, str(Hotkey(mods, name)))
                    self._recording = None
                else:
                    mods = frozenset(n for n in self._pressed if n in MODIFIERS)
                    fire = self._match_down(name, mods)
            elif not self._recording:
                fire = self._match_up(name)
        self._dispatch(fire, record)

    def release_all(self) -> None:
        """Alle als gedrueckt gemerkten Tasten vergessen (z. B. nach Sperrbildschirm)."""
        with self._lock:
            ups = [(slot, False) for slot in self._active]
            self._active.clear()
            self._pressed.clear()
        self._dispatch(ups, None)

    # ---------- intern ----------
    def _match_down(self, name: str, mods: frozenset) -> list[tuple[str, bool]]:
        best: dict[str, int] = {}
        for slot, hk in self._bindings.items():
            if hk.key == name and hk.mods <= mods:
                best[slot] = len(hk.mods)
        if not best:
            return []
        top = max(best.values())
        out = []
        for slot, score in best.items():
            if score == top:
                self._active[slot] = name
                out.append((slot, True))
        return out

    def _match_up(self, name: str) -> list[tuple[str, bool]]:
        out = []
        for slot, key in list(self._active.items()):
            if key == name:
                del self._active[slot]
                out.append((slot, False))
        return out

    def _dispatch(self, fire, record) -> None:
        for slot, down in fire:
            try:
                self._on_hotkey(slot, down)
            except Exception:  # Callback-Fehler duerfen den Hook nie stoppen
                pass
        if record and self._on_record:
            try:
                self._on_record(*record)
            except Exception:
                pass
