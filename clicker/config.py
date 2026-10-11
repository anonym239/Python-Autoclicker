"""Einstellungen + Profile: Laden, Pruefen, Speichern, Migration von v5."""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading

from .engine import ACTIONS, BUTTONS, MODES, ClickSettings, SmartSettings
from .keys import normalize_hotkey

CONFIG_NAME = "clicker_settings.json"
OLD_CONFIG_NAMES = ("ac_settings.json", "autoclicker_settings.json")  # v5
THEMES = ("grass", "diamond", "redstone", "amethyst", "gold")
HOTKEY_SLOTS = ("toggle", "stop", "next_profile")
MAX_PROFILES = 12
MAX_CPS = 1000.0
DEFAULT_PORT = 8765

PROFILE_DEFAULTS = {
    "name": "Standard",
    "button": "left",
    "mode": "toggle",
    "action": "click",
    "cps_min": 10.0,
    "cps_max": 10.0,
    "hold_ms": 0.0,
    "limit_seconds": 0.0,
    "limit_clicks": 0,
    "start_delay": 0.0,
}

# Minecraft-Startprofile. 1.9+ Schwert: Angriffsgeschwindigkeit 1,6/s = 625 ms Cooldown.
DEFAULT_PROFILES = [
    {"name": "Standard"},
    {"name": "PvP 1.8", "mode": "hold_mouse", "cps_min": 10, "cps_max": 14},
    {"name": "PvP 1.9+", "mode": "hold_mouse", "cps_min": 1.6, "cps_max": 1.6},
    {"name": "Bridging", "button": "right", "mode": "hold_mouse", "cps_min": 9, "cps_max": 12},
    {"name": "AFK Mob-Farm", "cps_min": 1.6, "cps_max": 1.6},
    {"name": "AFK Angeln", "button": "right", "action": "hold"},
    {"name": "Cobble-Miner", "action": "hold"},
]

DEFAULTS = {
    "version": 6,
    "active": "Standard",
    "profiles": [],
    "hotkeys": {"toggle": "f6", "stop": "", "next_profile": ""},
    "smart": {
        "window_lock": False,
        "window_match": "Minecraft, Lunar Client, Badlion, Feather, LabyMod",
        "pause_in_menus": False,
    },
    "app": {
        "sound": True,
        "always_on_top": False,
        "theme": "grass",
        "remote": False,
        "token": "",
        "port": DEFAULT_PORT,
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


def _clean_name(name, fallback="Profil") -> str:
    name = " ".join(str(name or "").split())[:24]
    return name or fallback


def sanitize_profile(raw: dict, base: dict | None = None) -> dict:
    p = dict(base or PROFILE_DEFAULTS)
    raw = raw or {}
    if "name" in raw:
        p["name"] = _clean_name(raw["name"], p.get("name", "Profil"))
    if raw.get("button") in BUTTONS:
        p["button"] = raw["button"]
    if raw.get("mode") in MODES:
        p["mode"] = raw["mode"]
    if raw.get("action") in ACTIONS:
        p["action"] = raw["action"]
    if "cps_min" in raw:
        p["cps_min"] = _num(raw["cps_min"], 0.1, MAX_CPS, p["cps_min"])
    if "cps_max" in raw:
        p["cps_max"] = _num(raw["cps_max"], 0.1, MAX_CPS, p["cps_max"])
    if p["cps_min"] > p["cps_max"]:
        if "cps_max" in raw and "cps_min" not in raw:
            p["cps_min"] = p["cps_max"]
        else:
            p["cps_max"] = p["cps_min"]
    if "hold_ms" in raw:
        p["hold_ms"] = _num(raw["hold_ms"], 0, 500, p["hold_ms"])
    if "limit_seconds" in raw:
        p["limit_seconds"] = _num(raw["limit_seconds"], 0, 86400, p["limit_seconds"])
    if "limit_clicks" in raw:
        p["limit_clicks"] = _num(raw["limit_clicks"], 0, 10**9, p["limit_clicks"], integer=True)
    if "start_delay" in raw:
        p["start_delay"] = _num(raw["start_delay"], 0, 60, p["start_delay"])
    return p


def _unique_name(name: str, taken) -> str:
    taken = {t.lower() for t in taken}
    if name.lower() not in taken:
        return name
    i = 2
    while f"{name[:20]} {i}".lower() in taken:
        i += 1
    return f"{name[:20]} {i}"


def _migrate_hotkey(text) -> str:
    t = str(text or "").strip().lower()
    t = KEY_ALIASES.get(t, t)
    return normalize_hotkey(t)


def migrate_v5(old: dict) -> tuple[dict, dict]:
    """v5-Einstellungen -> (Profil, Hotkeys)."""
    ms = _num(old.get("interval_ms"), 0.001, 600000, 100.0)
    cps = min(MAX_CPS, 1000.0 / ms)
    prof = sanitize_profile({
        "name": "Mein v5",
        "cps_min": cps, "cps_max": cps,
        "limit_seconds": old.get("auto_stop_sec", 0),
        "start_delay": old.get("delay_sec", 0),
    })
    start = _migrate_hotkey(old.get("hotkey_start")) or "f6"
    stop = _migrate_hotkey(old.get("hotkey_stop"))
    if stop == start:
        stop = ""
    return prof, {"toggle": start, "stop": stop, "next_profile": ""}


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
        d["profiles"] = [sanitize_profile(p) for p in DEFAULT_PROFILES]
        d["app"]["token"] = secrets.token_urlsafe(8)
        return d

    def load(self) -> None:
        with self._lock:
            raw = None
            if os.path.exists(self.path):
                try:
                    with open(self.path, encoding="utf-8") as f:
                        raw = json.load(f)
                except (OSError, ValueError):
                    raw = None
            if isinstance(raw, dict):
                self.data = self._sanitize(raw)
                return
            self.data = self._fresh()
            for name in OLD_CONFIG_NAMES:
                old_path = os.path.join(self.folder, name)
                try:
                    with open(old_path, encoding="utf-8") as f:
                        old = json.load(f)
                except (OSError, ValueError):
                    continue
                if isinstance(old, dict) and "interval_ms" in old:
                    prof, hks = migrate_v5(old)
                    self.data["profiles"].insert(0, prof)
                    self.data["active"] = prof["name"]
                    self.data["hotkeys"] = hks
                    self.data["app"]["always_on_top"] = _bool(old.get("always_on_top"))
                    self.migrated_from = name
                    break

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
        profiles = []
        for p in raw.get("profiles") or []:
            if isinstance(p, dict):
                sp = sanitize_profile(p)
                sp["name"] = _unique_name(sp["name"], [x["name"] for x in profiles])
                profiles.append(sp)
        if profiles:
            d["profiles"] = profiles[:MAX_PROFILES]
        names = [p["name"] for p in d["profiles"]]
        d["active"] = raw.get("active") if raw.get("active") in names else names[0]
        hk = raw.get("hotkeys") or {}
        for slot in HOTKEY_SLOTS:
            if slot in hk:
                d["hotkeys"][slot] = normalize_hotkey(hk[slot])
        self._apply_smart(d, raw.get("smart") or {})
        self._apply_app(d, raw.get("app") or {})
        st = raw.get("stats") or {}
        d["stats"]["lifetime_clicks"] = _num(st.get("lifetime_clicks", 0), 0, 10**15, 0, True)
        d["stats"]["best_cps"] = _num(st.get("best_cps", 0), 0, 100000, 0.0)
        return d

    @staticmethod
    def _apply_smart(d: dict, s: dict) -> None:
        sm = d["smart"]
        if "window_lock" in s:
            sm["window_lock"] = _bool(s["window_lock"])
        if "window_match" in s:
            text = ", ".join(x.strip() for x in str(s["window_match"]).split(",") if x.strip())
            sm["window_match"] = text[:200] or DEFAULTS["smart"]["window_match"]
        if "pause_in_menus" in s:
            sm["pause_in_menus"] = _bool(s["pause_in_menus"])

    @staticmethod
    def _apply_app(d: dict, a: dict) -> None:
        ap = d["app"]
        for key in ("sound", "always_on_top", "remote"):
            if key in a:
                ap[key] = _bool(a[key])
        if a.get("theme") in THEMES:
            ap["theme"] = a["theme"]
        tok = a.get("token")
        if isinstance(tok, str) and 8 <= len(tok) <= 64 and tok.replace("-", "").replace("_", "").isalnum():
            ap["token"] = tok
        if "port" in a:
            ap["port"] = _num(a["port"], 1024, 65535, DEFAULT_PORT, integer=True)

    # ─── Zugriff ─────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def active_profile(self) -> dict:
        with self._lock:
            for p in self.data["profiles"]:
                if p["name"] == self.data["active"]:
                    return dict(p)
            return dict(self.data["profiles"][0])

    def click_settings(self) -> ClickSettings:
        p = self.active_profile()
        return ClickSettings(**{k: p[k] for k in PROFILE_DEFAULTS if k != "name"})

    def smart_settings(self) -> SmartSettings:
        with self._lock:
            s = self.data["smart"]
            match = [m.strip() for m in s["window_match"].split(",") if m.strip()]
            return SmartSettings(window_lock=s["window_lock"], window_match=match,
                                 pause_in_menus=s["pause_in_menus"])

    # ─── Aenderungen ─────────────────────────────────────
    def update(self, patch: dict) -> set:
        """Teil-Update aus der UI. Gibt die geaenderten Bereiche zurueck."""
        changed = set()
        with self._lock:
            if isinstance(patch.get("profile"), dict):
                prof_patch = dict(patch["profile"])
                prof_patch.pop("name", None)  # Umbenennen nur ueber profile_op
                for i, p in enumerate(self.data["profiles"]):
                    if p["name"] == self.data["active"]:
                        self.data["profiles"][i] = sanitize_profile(prof_patch, p)
                changed.add("profile")
            if isinstance(patch.get("hotkeys"), dict):
                for slot in HOTKEY_SLOTS:
                    if slot in patch["hotkeys"]:
                        self.data["hotkeys"][slot] = normalize_hotkey(patch["hotkeys"][slot])
                changed.add("hotkeys")
            if isinstance(patch.get("smart"), dict):
                self._apply_smart(self.data, patch["smart"])
                changed.add("smart")
            if isinstance(patch.get("app"), dict):
                app = dict(patch["app"])
                app.pop("token", None)
                app.pop("port", None)
                self._apply_app(self.data, app)
                changed.add("app")
        return changed

    def set_hotkey(self, slot: str, text: str) -> None:
        if slot in HOTKEY_SLOTS:
            with self._lock:
                self.data["hotkeys"][slot] = normalize_hotkey(text)

    def new_token(self) -> str:
        with self._lock:
            self.data["app"]["token"] = secrets.token_urlsafe(8)
            return self.data["app"]["token"]

    def profile_op(self, op: str, name: str = "", new_name: str = "") -> str | None:
        """select / create / duplicate / rename / delete / next. -> Fehlertext oder None."""
        with self._lock:
            profs = self.data["profiles"]
            names = [p["name"] for p in profs]
            if op == "select":
                if name not in names:
                    return "Profil nicht gefunden"
                self.data["active"] = name
            elif op == "next":
                i = names.index(self.data["active"]) if self.data["active"] in names else -1
                self.data["active"] = names[(i + 1) % len(names)]
            elif op in ("create", "duplicate"):
                if len(profs) >= MAX_PROFILES:
                    return f"Maximal {MAX_PROFILES} Profile"
                base = self.active_profile() if op == "duplicate" else dict(PROFILE_DEFAULTS)
                base["name"] = _unique_name(_clean_name(new_name or base["name"]), names)
                profs.append(sanitize_profile(base))
                self.data["active"] = base["name"]
            elif op == "rename":
                cur = name or self.data["active"]
                if cur not in names:
                    return "Profil nicht gefunden"
                clean = _clean_name(new_name, "")
                if not clean:
                    return "Name fehlt"
                others = [n for n in names if n != cur]
                clean = _unique_name(clean, others)
                profs[names.index(cur)]["name"] = clean
                if self.data["active"] == cur:
                    self.data["active"] = clean
            elif op == "delete":
                cur = name or self.data["active"]
                if cur not in names:
                    return "Profil nicht gefunden"
                if len(profs) <= 1:
                    return "Das letzte Profil bleibt"
                idx = names.index(cur)
                profs.pop(idx)
                if self.data["active"] == cur:
                    self.data["active"] = profs[max(0, idx - 1)]["name"]
            else:
                return "Unbekannte Aktion"
        return None
