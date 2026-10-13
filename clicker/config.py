"""Einstellungen: 4 feste Modi links, eigene Hotkeys, ein paar Optionen."""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading

from .engine import ACTIONS, BUTTONS, ClickSettings, SmartSettings
from .keys import normalize_hotkey

CONFIG_NAME = "clicker_settings.json"
OLD_CONFIG_NAMES = ("ac_settings.json", "autoclicker_settings.json")  # v5
THEMES = ("system", "light", "dark")
LANGUAGES = ("auto", "de", "en", "es", "fr", "it", "pt", "nl", "sv", "nb", "da", "fi", "pl", "cs", "sk", "hu", "ro", "el", "bg", "ru", "uk", "tr", "ja", "zh", "ko")  # muss zu web/i18n.js passen
HOTKEY_ACTIONS = ("toggle", "on", "off")  # An/Aus, nur an, nur aus
MAX_HOTKEYS = 8
MAX_ICON_LEN = 4000  # data:-URL eines 16x16-Bildes
MAX_CPS = 1000.0
DEFAULT_PORT = 8765
VARIATION = 0.12  # +-12 % bei "zufaellige Abweichung"

# Die Modi in der linken Leiste. Modus-Art ist fest, Tempo/Taste pro Modus einstellbar.
PRESETS = {
    "standard": {"name": "Standard", "mode": "toggle", "button": "left", "cps": 10.0},
    "pvp": {"name": "Minecraft PvP", "mode": "hold_mouse", "button": "left", "cps": 13.0},
    "boost": {"name": "CPS-Boost", "mode": "boost", "button": "left", "boost": 2},
    # 1,6 CPS = 625 ms = Schwert-Cooldown ab Minecraft 1.9
    "afk": {"name": "AFK-Farm", "mode": "toggle", "button": "left", "cps": 1.6},
}
PRESET_ORDER = ("standard", "pvp", "boost", "afk")

DEFAULTS = {
    "version": 6,
    "preset": "standard",
    "presets": {},
    "hotkeys": [{"key": "f6", "action": "toggle"}],
    # Angelernte Werkzeuge (PvP/Boost): Hotbar-Platz 1–9 + Bild des Items
    "tools": [],
    "general": {
        "vary": False,
        "auto_stop": 0.0,
        "start_delay": 0.0,
        "window_lock": False,
        "window_match": "Minecraft, Lunar Client, Badlion, Feather, LabyMod",
        "sound": True,
        "always_on_top": False,
        "theme": "system",
        "language": "auto",           # auto = Sprache von Windows
        "token": "",
        "port": DEFAULT_PORT,
        "tutorial_done": False,
        "update_skip": "",            # diese Version nicht mehr anzeigen
        "update_snooze_until": 0.0,   # "In 5 Tagen erinnern" (Unix-Zeit)
    },
    "stats": {"lifetime_clicks": 0, "best_cps": 0.0},
}

KEY_ALIASES = {
    "prior": "pageup", "next": "pagedown", "page up": "pageup", "page down": "pagedown",
    "return": "enter", "escape": "esc", "control": "ctrl", "control_l": "ctrl",
    "control_r": "ctrl", "shift_l": "shift", "shift_r": "shift", "alt_l": "alt",
    "alt_r": "alt", "caps_lock": "capslock", "caps lock": "capslock",
    "num_lock": "numlock", "scroll_lock": "scrolllock", "print": "printscreen",
    "print screen": "printscreen", "windows": "win", "left windows": "win",
}


def _num(value, lo, hi, default, integer=False):
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    v = min(hi, max(lo, v))
    return int(round(v)) if integer else round(v, 3)


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "ja", "an", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _preset_defaults(pid: str) -> dict:
    p = PRESETS[pid]
    return {"button": p["button"], "cps": p.get("cps", 10.0), "boost": p.get("boost", 2), "action": "click"}


def sanitize_preset(raw: dict, base: dict) -> dict:
    p = dict(base)
    raw = raw or {}
    if raw.get("button") in BUTTONS:
        p["button"] = raw["button"]
    if "cps" in raw:
        p["cps"] = _num(raw["cps"], 0.1, MAX_CPS, p["cps"])
    if "boost" in raw:
        p["boost"] = _num(raw["boost"], 2, 3, p["boost"], integer=True)
    if raw.get("action") in ACTIONS:
        p["action"] = raw["action"]
    return p


def _migrate_hotkey(text) -> str:
    t = str(text or "").strip().lower()
    return normalize_hotkey(KEY_ALIASES.get(t, t))


def sanitize_tools(items) -> list:
    out, seen = [], set()
    for t in items:
        if not isinstance(t, dict):
            continue
        slot = t.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= 9 or slot in seen:
            continue
        icon = t.get("icon")
        if not (isinstance(icon, str) and icon.startswith("data:image/png;base64,") and len(icon) <= MAX_ICON_LEN):
            icon = ""
        seen.add(slot)
        out.append({"slot": slot, "icon": icon})
    return sorted(out, key=lambda t: t["slot"])


def sanitize_hotkeys(raw) -> list:
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        key = normalize_hotkey(item.get("key", ""))
        action = item.get("action") if item.get("action") in HOTKEY_ACTIONS else "toggle"
        if key and key not in seen and len(out) < MAX_HOTKEYS:
            seen.add(key)
            out.append({"key": key, "action": action})
    return out


def user_data_dir(fallback: str) -> str:
    """Ordner fuer die Einstellungen der installierten .exe (immer beschreibbar)."""
    base = os.environ.get("APPDATA")
    if not base:
        return fallback
    path = os.path.join(base, "AutoClicker")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        return fallback


class Config:
    def __init__(self, folder: str):
        self.folder = folder
        self.path = os.path.join(folder, CONFIG_NAME)
        self._lock = threading.RLock()
        self.data = self._fresh()
        self.migrated_from = None

    # ─── Laden / Speichern ───────────────────────────────
    @staticmethod
    def _fresh() -> dict:
        d = copy.deepcopy(DEFAULTS)
        d["presets"] = {pid: _preset_defaults(pid) for pid in PRESET_ORDER}
        d["general"]["token"] = secrets.token_urlsafe(8)
        return d

    def load(self) -> None:
        with self._lock:
            raw = None
            try:
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                raw = None
            if isinstance(raw, dict) and "general" in raw:
                self.data = self._sanitize(raw)
                return
            self.data = self._fresh()
            for name in OLD_CONFIG_NAMES:
                try:
                    with open(os.path.join(self.folder, name), encoding="utf-8") as f:
                        old = json.load(f)
                except (OSError, ValueError):
                    continue
                if isinstance(old, dict) and "interval_ms" in old:
                    self._migrate_v5(old)
                    self.migrated_from = name
                    break

    def _migrate_v5(self, old: dict) -> None:
        ms = _num(old.get("interval_ms"), 0.001, 600000, 100.0)
        self.data["presets"]["standard"]["cps"] = round(min(MAX_CPS, 1000.0 / ms), 3)
        start = _migrate_hotkey(old.get("hotkey_start")) or "f6"
        stop = _migrate_hotkey(old.get("hotkey_stop"))
        if stop and stop != start:  # v5 hatte getrennte Start- und Stopp-Tasten
            self.data["hotkeys"] = [{"key": start, "action": "on"}, {"key": stop, "action": "off"}]
        else:
            self.data["hotkeys"] = [{"key": start, "action": "toggle"}]
        g = self.data["general"]
        g["auto_stop"] = _num(old.get("auto_stop_sec", 0), 0, 86400, 0.0)
        g["always_on_top"] = _bool(old.get("always_on_top"))

    def save(self) -> bool:
        with self._lock:
            text = json.dumps(self.data, indent=2, ensure_ascii=False)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def _sanitize(self, raw: dict) -> dict:
        d = self._fresh()
        presets = raw.get("presets") or {}
        for pid in PRESET_ORDER:
            if isinstance(presets.get(pid), dict):
                d["presets"][pid] = sanitize_preset(presets[pid], d["presets"][pid])
        if raw.get("preset") in PRESETS:
            d["preset"] = raw["preset"]
        if isinstance(raw.get("tools"), list):
            d["tools"] = sanitize_tools(raw["tools"])
        if isinstance(raw.get("hotkeys"), list):
            d["hotkeys"] = sanitize_hotkeys(raw["hotkeys"])
        elif "hotkey" in raw:  # Version 6.0.0 hatte nur einen Hotkey
            key = normalize_hotkey(raw["hotkey"])
            d["hotkeys"] = [{"key": key, "action": "toggle"}] if key else []
        self._apply_general(d, raw.get("general") or {}, allow_private=True)
        st = raw.get("stats") or {}
        d["stats"]["lifetime_clicks"] = _num(st.get("lifetime_clicks", 0), 0, 10**15, 0, True)
        d["stats"]["best_cps"] = _num(st.get("best_cps", 0), 0, 100000, 0.0)
        return d

    @staticmethod
    def _apply_general(d: dict, g: dict, allow_private: bool = False) -> None:
        out = d["general"]
        for key in ("vary", "window_lock", "sound", "always_on_top", "tutorial_done"):
            if key in g:
                out[key] = _bool(g[key])
        if "auto_stop" in g:
            out["auto_stop"] = _num(g["auto_stop"], 0, 86400, out["auto_stop"])
        if "start_delay" in g:
            out["start_delay"] = _num(g["start_delay"], 0, 60, out["start_delay"])
        if "window_match" in g:
            text = ", ".join(x.strip() for x in str(g["window_match"]).split(",") if x.strip())
            out["window_match"] = text[:200] or DEFAULTS["general"]["window_match"]
        if "update_skip" in g:
            out["update_skip"] = str(g["update_skip"] or "")[:20]
        if "update_snooze_until" in g:
            out["update_snooze_until"] = _num(g["update_snooze_until"], 0, 10**11, 0.0)
        if g.get("theme") in THEMES:
            out["theme"] = g["theme"]
        if g.get("language") in LANGUAGES:
            out["language"] = g["language"]
        if allow_private:
            tok = g.get("token")
            if isinstance(tok, str) and 8 <= len(tok) <= 64 and tok.replace("-", "").replace("_", "").isalnum():
                out["token"] = tok
            if "port" in g:
                out["port"] = _num(g["port"], 1024, 65535, DEFAULT_PORT, integer=True)

    # ─── Zugriff ─────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    @property
    def preset_id(self) -> str:
        return self.data["preset"]

    def mode(self) -> str:
        return PRESETS[self.data["preset"]]["mode"]

    def current(self) -> dict:
        with self._lock:
            return dict(self.data["presets"][self.data["preset"]])

    def click_settings(self) -> ClickSettings:
        with self._lock:
            p = self.data["presets"][self.data["preset"]]
            g = self.data["general"]
            cps = p["cps"]
            lo = max(0.1, round(cps * (1 - VARIATION), 2)) if g["vary"] else cps
            hi = min(MAX_CPS, round(cps * (1 + VARIATION), 2)) if g["vary"] else cps
            return ClickSettings(button=p["button"], mode=self.mode(), cps_min=lo, cps_max=hi,
                                 boost=p["boost"], action=p["action"], limit_seconds=g["auto_stop"],
                                 start_delay=g["start_delay"])

    def smart_settings(self) -> SmartSettings:
        with self._lock:
            g = self.data["general"]
            match = [m.strip() for m in g["window_match"].split(",") if m.strip()]
            return SmartSettings(window_lock=g["window_lock"], window_match=match)

    # ─── Aenderungen ─────────────────────────────────────
    def update(self, patch: dict) -> set:
        """Teil-Update aus der Oberflaeche. Gibt die geaenderten Bereiche zurueck."""
        changed = set()
        with self._lock:
            if isinstance(patch.get("preset"), dict):
                pid = self.data["preset"]
                self.data["presets"][pid] = sanitize_preset(patch["preset"], self.data["presets"][pid])
                changed.add("preset")
            if isinstance(patch.get("general"), dict):
                self._apply_general(self.data, patch["general"])
                changed.add("general")
        return changed

    def select(self, pid: str) -> bool:
        if pid not in PRESETS:
            return False
        with self._lock:
            self.data["preset"] = pid
        return True

    # ─── Hotkeys ─────────────────────────────────────────
    def hotkeys(self) -> list:
        with self._lock:
            return [dict(h) for h in self.data["hotkeys"]]

    def set_hotkey(self, index, key: str) -> str | None:
        """index None = neuen Hotkey anlegen. -> Fehlercode (e_…, siehe web/i18n.js) oder None."""
        key = normalize_hotkey(key)
        if not key:
            return "e_key_invalid"
        with self._lock:
            hks = self.data["hotkeys"]
            for i, h in enumerate(hks):
                if h["key"] == key and i != index:
                    return "e_key_taken"
            if index is None:
                if len(hks) >= MAX_HOTKEYS:
                    return "e_max_hotkeys"
                hks.append({"key": key, "action": "toggle"})
            elif 0 <= index < len(hks):
                hks[index]["key"] = key
            else:
                return "e_not_found"
        return None

    def set_hotkey_action(self, index: int, action: str) -> bool:
        with self._lock:
            hks = self.data["hotkeys"]
            if action in HOTKEY_ACTIONS and 0 <= index < len(hks):
                hks[index]["action"] = action
                return True
        return False

    def delete_hotkey(self, index: int) -> bool:
        with self._lock:
            hks = self.data["hotkeys"]
            if 0 <= index < len(hks):
                hks.pop(index)
                return True
        return False

    # ─── Werkzeuge ───────────────────────────────────────
    def tools(self) -> list:
        with self._lock:
            return [dict(t) for t in self.data["tools"]]

    def tool_slots(self) -> frozenset:
        with self._lock:
            return frozenset(t["slot"] for t in self.data["tools"])

    def learn_tool(self, slot: int, icon: str) -> None:
        """Platz als Werkzeug speichern (gleicher Platz -> Bild ersetzen)."""
        with self._lock:
            tools = [t for t in self.data["tools"] if t["slot"] != slot]
            tools.append({"slot": slot, "icon": icon})
            self.data["tools"] = sanitize_tools(tools)

    def delete_tool(self, slot: int) -> bool:
        with self._lock:
            before = len(self.data["tools"])
            self.data["tools"] = [t for t in self.data["tools"] if t["slot"] != slot]
            return len(self.data["tools"]) != before

    def new_token(self) -> str:
        with self._lock:
            self.data["general"]["token"] = secrets.token_urlsafe(8)
            return self.data["general"]["token"]
