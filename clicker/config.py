"""Einstellungen: 4 feste Modi links, eigene Hotkeys, ein paar Optionen."""

from __future__ import annotations

import copy
import json
import os
import re
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
MAX_ICON_LEN = 8000  # data:-URL eines 16x16-Bildes
MAX_PHOTO_LEN = 40000  # Foto des Hotbar-Platzes (nur Anzeige)
MAX_TOOLS = 30  # pro Kit
MAX_KITS = 10
MAX_KIT_NAME = 30
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

# Spiele im Home-Menue: Fenstername fuer "Nur klicken, wenn das Spiel vorne ist".
# Nur Minecraft hat Werkzeug-Erkennung (Hotbar) und Minecraft-Namen bei den Modi.
GAMES = {
    "minecraft": "Minecraft, Lunar Client, Badlion, Feather, LabyMod",
    "roblox": "Roblox",
    "terraria": "Terraria",
    "cookie": "Cookie Clicker",
    "other": "",
}
MAX_PINS = 12
DEFAULT_PINS = [
    {"name": "YouTube", "url": "https://www.youtube.com"},
    {"name": "Spotify", "url": "https://open.spotify.com", "app": "spotify:"},
    {"name": "Discord", "url": "https://discord.com/app", "app": "discord:"},
    {"name": "Twitch", "url": "https://www.twitch.tv"},
]

DEFAULTS = {
    "version": 6,
    "preset": "standard",
    "presets": {},
    "hotkeys": [{"key": "f6", "action": "toggle"}],
    # Kits = Saetze angelernter Werkzeuge (PvP/Boost), z. B. eins pro Server/Spielmodus.
    # Werkzeug = Umriss des Items (256 Bit hex) + Bild
    "kits": [{"name": "Kit 1", "tools": []}],
    "kit": 0,                         # gerade benutztes Kit
    # Home-Menue: angepinnte Seiten/Programme. url = Webseite (eigenes Fenster),
    # app = Programm oder Protokoll (z. B. "spotify:") – wird bevorzugt, wenn installiert
    "pins": DEFAULT_PINS,
    "general": {
        "vary": False,
        "auto_stop": 0.0,
        "start_delay": 0.0,
        "window_lock": False,
        "menu_pause": True,           # Minecraft: in Inventar, Truhen, Chat, Pause-Menue nicht klicken
        "window_match": "Minecraft, Lunar Client, Badlion, Feather, LabyMod",
        "sound": True,
        "always_on_top": False,
        "theme": "system",
        "language": "auto",           # auto = Sprache von Windows
        "token": "",
        "port": DEFAULT_PORT,
        "tutorial_done": False,
        "learn_hotkey_on": False,     # Hotkey startet "Werkzeug anlernen" direkt im Spiel
        "learn_hotkey": "f7",
        "game": "",                   # gewaehltes Spiel (siehe GAMES), leer = noch nicht gewaehlt
        "home_version": "",           # Version, bei der das Home-Menue zuletzt gezeigt wurde
        "profile_pic": "",            # Google-/YouTube-Profilbild (Adresse), nach dem Anmelden
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


# Aeusserste Pixelreihe des 16x16-Felds – gehoert nie zum Item (seit 6.10)
_MASK_RIM = sum(1 << (y * 16 + x) for y in range(16) for x in range(16) if x in (0, 15) or y in (0, 15))


def sanitize_tools(items) -> list:
    out = []
    for t in items:
        if not isinstance(t, dict):
            continue
        mask = t.get("mask")
        if not (isinstance(mask, str) and len(mask) == 64 and all(c in "0123456789abcdef" for c in mask)):
            continue  # z. B. alte Eintraege aus 6.6 (nur Platz-Nummer)
        bits = int(mask, 16)
        if bits & _MASK_RIM or bin(bits).count("1") > 150:
            continue  # alte Eintraege bis 6.9: Rand des Platzes mitgezaehlt -> neu anlernen
        icon = t.get("icon")
        if not (isinstance(icon, str) and icon.startswith("data:image/png;base64,") and len(icon) <= MAX_ICON_LEN):
            icon = ""
        entry = {"mask": mask, "icon": icon}
        photo = t.get("photo")
        if isinstance(photo, str) and photo.startswith("data:image/png;base64,") and len(photo) <= MAX_PHOTO_LEN:
            entry["photo"] = photo
        out.append(entry)
    return out[:MAX_TOOLS]


_FILE_ENDINGS = {"exe", "bat", "cmd", "lnk", "url", "msi", "ps1", "vbs", "dll", "jar", "txt"}
_HOST = re.compile(r"^(localhost|[a-z0-9-]+(\.[a-z0-9-]+)+)(:\d{1,5})?$", re.I)


def web_url(text) -> str:
    """Eingabe ("youtube.com", "https://…") -> https-Adresse, sonst "" (nur http/https)."""
    t = str(text or "").strip()
    if not t or len(t) > 500 or any(c.isspace() for c in t):
        return ""
    if not t.lower().startswith(("http://", "https://")):
        t = "https://" + t
    host = t.split("://", 1)[1].split("/")[0].split("?")[0].split("#")[0]
    if not _HOST.match(host) or host.split(":")[0].rsplit(".", 1)[-1].lower() in _FILE_ENDINGS:
        return ""  # "spiel.exe" ist ein Programm, keine Webseite
    return t


def app_target(text) -> str:
    """Programm (Windows-Pfad zu .exe/.lnk/.url) oder Protokoll wie "spotify:" – sonst ""."""
    t = str(text or "").strip().strip('"')
    if not t or len(t) > 260:
        return ""
    if re.match(r"^[a-zA-Z]:\\", t) and t.lower().endswith((".exe", ".lnk", ".url")):
        return t
    scheme = t.lower()
    if re.match(r"^[a-z][a-z0-9+.-]{1,30}:(//)?$", scheme) and not scheme.startswith(("http", "file", "javascript", "data")):
        return scheme
    return ""


# Profilbilder liegen bei Google auf diesen Servern – andere Adressen werden nie angezeigt
_PIC_HOSTS = ("googleusercontent.com", "ggpht.com", "ytimg.com")


def profile_pic_url(text) -> str:
    t = str(text or "").strip()
    if len(t) > 1000 or not t.startswith("https://"):
        return ""
    host = t[8:].split("/")[0].lower()
    return t if any(host == h or host.endswith("." + h) for h in _PIC_HOSTS) else ""


def pin_name(url: str, app: str) -> str:
    """Name fuer eine angepinnte Seite / ein Programm, wenn keiner angegeben ist."""
    if url:
        host = url.split("://", 1)[1].split("/")[0].split(":")[0]
        host = host[4:] if host.startswith("www.") else host
        return host.split(".")[0].capitalize() or "Web"
    base = re.split(r"[\\/]", app.rstrip(":/"))[-1]
    return (base.rsplit(".", 1)[0] if "\\" in app else base).capitalize() or "App"


def sanitize_pins(raw) -> list:
    out = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or len(out) >= MAX_PINS:
            continue
        url, app = web_url(p.get("url")), app_target(p.get("app"))
        if not url and not app:
            continue
        entry = {"name": " ".join(str(p.get("name") or "").split())[:24] or pin_name(url, app)}
        if url:
            entry["url"] = url
        if app:
            entry["app"] = app
        out.append(entry)
    return out


def kit_name(name, fallback: str = "Kit") -> str:
    text = " ".join(str(name or "").split())[:MAX_KIT_NAME]
    return text or fallback


def sanitize_kits(raw) -> list:
    out = []
    for k in raw if isinstance(raw, list) else []:
        if isinstance(k, dict) and len(out) < MAX_KITS:
            tools = sanitize_tools(k.get("tools") if isinstance(k.get("tools"), list) else [])
            out.append({"name": kit_name(k.get("name"), f"Kit {len(out) + 1}"), "tools": tools})
    return out


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
        if isinstance(raw.get("pins"), list):
            d["pins"] = sanitize_pins(raw["pins"])
        if "game" not in (raw.get("general") or {}):
            d["general"]["game"] = "minecraft"  # bis 6.17 gab es nur Minecraft
        kits = sanitize_kits(raw.get("kits"))
        if kits:
            d["kits"] = kits
            if isinstance(raw.get("kit"), int) and 0 <= raw["kit"] < len(kits):
                d["kit"] = raw["kit"]
        elif isinstance(raw.get("tools"), list):  # bis 6.14: nur ein Satz Werkzeuge
            d["kits"][0]["tools"] = sanitize_tools(raw["tools"])
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
        for key in ("vary", "window_lock", "sound", "always_on_top", "tutorial_done", "learn_hotkey_on",
                    "menu_pause"):
            if key in g:
                out[key] = _bool(g[key])
        if "auto_stop" in g:
            out["auto_stop"] = _num(g["auto_stop"], 0, 86400, out["auto_stop"])
        if "start_delay" in g:
            out["start_delay"] = _num(g["start_delay"], 0, 60, out["start_delay"])
        if "window_match" in g:
            text = ", ".join(x.strip() for x in str(g["window_match"]).split(",") if x.strip())
            out["window_match"] = text[:200] or DEFAULTS["general"]["window_match"]
        if "learn_hotkey" in g:
            out["learn_hotkey"] = normalize_hotkey(str(g["learn_hotkey"] or "")) or out["learn_hotkey"]
        if "update_skip" in g:
            out["update_skip"] = str(g["update_skip"] or "")[:20]
        if "update_snooze_until" in g:
            out["update_snooze_until"] = _num(g["update_snooze_until"], 0, 10**11, 0.0)
        if g.get("theme") in THEMES:
            out["theme"] = g["theme"]
        if g.get("language") in LANGUAGES:
            out["language"] = g["language"]
        if g.get("game") in GAMES and g["game"] != out["game"]:
            # Fenstername mitwechseln, solange er nicht selbst geaendert wurde
            if GAMES[g["game"]] and out["window_match"] in GAMES.values():
                out["window_match"] = GAMES[g["game"]]
            out["game"] = g["game"]
        if "home_version" in g:
            out["home_version"] = str(g["home_version"] or "")[:20]
        if allow_private:
            out["profile_pic"] = profile_pic_url(g.get("profile_pic", out["profile_pic"]))
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
            minecraft = g["game"] in ("minecraft", "")
            menu_windows = [m.strip() for m in GAMES["minecraft"].split(",")] + match if minecraft else []
            return SmartSettings(window_lock=g["window_lock"], window_match=match,
                                 menu_pause=g["menu_pause"] and minecraft, menu_windows=menu_windows)

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
            if key == self._learn_key():
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

    def _learn_key(self) -> str:
        g = self.data["general"]
        return g["learn_hotkey"] if g["learn_hotkey_on"] else ""

    def learn_hotkey(self) -> str:
        """Taste fuer "Werkzeug anlernen" – leer, wenn ausgeschaltet."""
        with self._lock:
            return self._learn_key()

    def set_learn_hotkey(self, key: str) -> str | None:
        key = normalize_hotkey(key)
        if not key:
            return "e_key_invalid"
        with self._lock:
            if any(h["key"] == key for h in self.data["hotkeys"]):
                return "e_key_taken"
            self.data["general"]["learn_hotkey"] = key
            self.data["general"]["learn_hotkey_on"] = True
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
    def _tools(self) -> list:
        return self.data["kits"][self.data["kit"]]["tools"]

    def tools(self) -> list:
        """Werkzeuge des gerade gewaehlten Kits."""
        with self._lock:
            return [dict(t) for t in self._tools()]

    def learn_tool(self, mask: str, icon: str, replace: int = -1, photo: str = "") -> bool:
        """Werkzeug speichern. replace = Index eines gleichen Werkzeugs (wird ersetzt).
        icon = ausgeschnittenes Item (fuer die Erkennung), photo = Platz 1:1 (zum Anzeigen).
        -> False, wenn das Kit schon voll ist."""
        with self._lock:
            tools = self._tools()
            entry = {"mask": mask, "icon": icon}
            if photo:
                entry["photo"] = photo
            if 0 <= replace < len(tools):
                tools[replace] = entry
            elif len(tools) >= MAX_TOOLS:
                return False
            else:
                tools.append(entry)
            tools[:] = sanitize_tools(tools)
            return True

    def import_kit(self, name, items) -> tuple[int, str | None]:
        """Kit aus einer Datei uebernehmen: ins gewaehlte Kit, wenn es leer ist, sonst als
        neues Kit. Gibt es dieselben Werkzeuge schon als Kit, wird nur dieses gewaehlt.
        -> (Anzahl neuer Werkzeuge, Fehlercode oder None)"""
        new = sanitize_tools(items if isinstance(items, list) else [])
        masks = {t["mask"] for t in new}
        with self._lock:
            kits = self.data["kits"]
            for i, k in enumerate(kits):
                if masks and {t["mask"] for t in k["tools"]} == masks:
                    self.data["kit"] = i
                    return 0, None
            if self._tools():
                if len(kits) >= MAX_KITS:
                    return 0, "e_max_kits"
                kits.append({"name": "", "tools": []})
                self.data["kit"] = len(kits) - 1
            kit = kits[self.data["kit"]]
            kit["tools"] = new
            if name or not kit["name"]:
                kit["name"] = kit_name(name, f"Kit {self.data['kit'] + 1}")
            return len(new), None

    def delete_tool(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self._tools()):
                self._tools().pop(index)
                return True
        return False

    # ─── Kits ────────────────────────────────────────────
    def kits(self) -> list:
        """-> [{"name", "count"}] fuer die Oberflaeche."""
        with self._lock:
            return [{"name": k["name"], "count": len(k["tools"])} for k in self.data["kits"]]

    def kit_index(self) -> int:
        return self.data["kit"]

    def active_kit_name(self) -> str:
        with self._lock:
            return self.data["kits"][self.data["kit"]]["name"]

    def select_kit(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self.data["kits"]):
                self.data["kit"] = index
                return True
        return False

    def new_kit(self, name: str = "") -> str | None:
        """Leeres Kit anlegen und auswaehlen. -> Fehlercode oder None."""
        with self._lock:
            kits = self.data["kits"]
            if len(kits) >= MAX_KITS:
                return "e_max_kits"
            kits.append({"name": kit_name(name, f"Kit {len(kits) + 1}"), "tools": []})
            self.data["kit"] = len(kits) - 1
        return None

    def rename_kit(self, index: int, name: str) -> bool:
        with self._lock:
            if 0 <= index < len(self.data["kits"]):
                self.data["kits"][index]["name"] = kit_name(name, self.data["kits"][index]["name"])
                return True
        return False

    def delete_kit(self, index: int) -> bool:
        """Kit loeschen. Das letzte Kit bleibt immer da (wird nur geleert)."""
        with self._lock:
            kits = self.data["kits"]
            if not 0 <= index < len(kits):
                return False
            if len(kits) == 1:
                kits[0] = {"name": "Kit 1", "tools": []}
            else:
                kits.pop(index)
            if self.data["kit"] >= len(kits) or self.data["kit"] > index:
                self.data["kit"] = max(0, self.data["kit"] - 1)
        return True

    # ─── Home-Menue ──────────────────────────────────────
    def game(self) -> str:
        return self.data["general"]["game"]

    def set_profile_pic(self, url: str) -> bool:
        """-> True, wenn sich das Bild geaendert hat ("" = abgemeldet). Fremde Adressen: nichts."""
        clean = profile_pic_url(url)
        if url and not clean:
            return False
        url = clean
        with self._lock:
            if self.data["general"]["profile_pic"] == url:
                return False
            self.data["general"]["profile_pic"] = url
            return True

    def pins(self) -> list:
        with self._lock:
            return [dict(p) for p in self.data["pins"]]

    def add_pin(self, name: str, target: str) -> str | None:
        """Seite ("youtube.com") oder Programm ("C:\\…\\Spiel.exe", "spotify:") anpinnen.
        -> Fehlercode oder None."""
        app = app_target(target)
        url = "" if app else web_url(target)
        if not url and not app:
            return "e_pin_target"
        with self._lock:
            pins = self.data["pins"]
            if len(pins) >= MAX_PINS:
                return "e_max_pins"
            pins.extend(sanitize_pins([{"name": name, "url": url, "app": app}]))
        return None

    def remove_pin(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self.data["pins"]):
                self.data["pins"].pop(index)
                return True
        return False

    def new_token(self) -> str:
        with self._lock:
            self.data["general"]["token"] = secrets.token_urlsafe(8)
            return self.data["general"]["token"]
