"""
AutoClicker v5
Features:
  - Klick-Interval in ms + Presets
  - Auto-Stop Timer (nach X Sekunden)
  - Start-Delay (Countdown)
  - Live Klick-Zaehler + Live CPS
  - Immer im Vordergrund
  - Benutzerdefinierte Hotkeys (F-Tasten, Buchstaben, Kombinationen)
  - Einstellungen automatisch speichern/laden
  - Funktioniert auch minimiert
"""

import tkinter as tk
import threading
import time
import sys
import ctypes
import json
import os

try:
    import keyboard
except ImportError:
    print("Fehlendes Modul!  pip install keyboard")
    input("Enter zum Beenden...")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
# WINDOWS API: LINKSKLICK via SendInput
# SendInput triggert keine externen Hooks → zaehlt sich nicht selbst
# ═══════════════════════════════════════════════════════════
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_", _UNION)]

def _send_click():
    down = _INPUT(type=0, _=_UNION(mi=_MOUSEINPUT(dwFlags=0x0002)))
    up   = _INPUT(type=0, _=_UNION(mi=_MOUSEINPUT(dwFlags=0x0004)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
    ctypes.windll.user32.SendInput(1, ctypes.byref(up),   ctypes.sizeof(_INPUT))

# ═══════════════════════════════════════════════════════════
# EINSTELLUNGEN
# ═══════════════════════════════════════════════════════════
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ac_settings.json")

DEFAULTS = {
    "interval_ms":   "100",
    "hotkey_start":  "f1",
    "hotkey_stop":   "f2",
    "auto_stop_sec": "0",
    "delay_sec":     "0",
    "always_on_top": False,
}

def _load_cfg():
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
        m = dict(DEFAULTS)
        m.update(d)
        return m
    except Exception:
        return dict(DEFAULTS)

def _save_cfg():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "interval_ms":   iv.get(),
                "hotkey_start":  S["hk_start"],
                "hotkey_stop":   S["hk_stop"],
                "auto_stop_sec": autostop_v.get(),
                "delay_sec":     delay_v.get(),
                "always_on_top": S["on_top"],
            }, f, indent=2)
        _status("Gespeichert!", C_GREEN)
        root.after(2000, lambda: _status(
            "Laeuft..." if S["running"] else "Gestoppt",
            C_GREEN if S["running"] else C_ORANGE))
    except Exception as e:
        _status(f"Fehler: {e}", C_RED)

# ═══════════════════════════════════════════════════════════
# ZUSTAND
# ═══════════════════════════════════════════════════════════
S = {
    "running":   False,
    "hk_start":  "f1",
    "hk_stop":   "f2",
    "rec_for":   None,   # "start" | "stop" | None
    "on_top":    False,
    "count":     0,
    "times":     [],
}

# ═══════════════════════════════════════════════════════════
# KLICK-ENGINE
# ═══════════════════════════════════════════════════════════
def _click_loop(interval_s, end_ts):
    while S["running"]:
        if end_ts and time.perf_counter() >= end_ts:
            root.after(0, stop_clicking)
            return
        _send_click()
        S["count"] += 1
        now = time.perf_counter()
        S["times"].append(now)
        # Nur letzte Sekunde fuer CPS
        if len(S["times"]) > 5000:
            S["times"] = S["times"][-2000:]
        # Warten
        if interval_s < 0.005:
            t = time.perf_counter() + interval_s
            while time.perf_counter() < t:
                pass
        else:
            time.sleep(interval_s)

def _stats_loop():
    while S["running"]:
        now = time.perf_counter()
        cps = sum(1 for t in S["times"] if now - t <= 1.0)
        c   = S["count"]
        root.after(0, lambda c=c, s=cps: _update_stats(c, s))
        time.sleep(0.15)

def _delayed_start(interval_s, end_ts, delay_s):
    deadline = time.perf_counter() + delay_s
    while time.perf_counter() < deadline:
        r = deadline - time.perf_counter()
        root.after(0, lambda r=r: _status(f"Start in {r:.1f}s ...", C_ORANGE))
        time.sleep(0.1)
    root.after(0, lambda: _begin(interval_s, end_ts))

# ═══════════════════════════════════════════════════════════
# START / STOP
# ═══════════════════════════════════════════════════════════
def start_clicking():
    if S["running"]:
        return
    try:
        ms = float(iv.get())
        if ms <= 0:
            _status("Interval muss > 0!", C_RED)
            return
    except ValueError:
        _status("Ungueltige ms-Eingabe!", C_RED)
        return

    try:    autostop = float(autostop_v.get())
    except: autostop = 0
    try:    delay    = float(delay_v.get())
    except: delay    = 0

    end_ts = (time.perf_counter() + autostop) if autostop > 0 else None
    interval_s = ms / 1000.0

    _lock(True)

    if delay > 0:
        _status(f"Start in {delay:.1f}s ...", C_ORANGE)
        threading.Thread(target=_delayed_start,
                         args=(interval_s, end_ts, delay),
                         daemon=True).start()
    else:
        _begin(interval_s, end_ts)

def _begin(interval_s, end_ts):
    S["running"] = True
    threading.Thread(target=_click_loop, args=(interval_s, end_ts), daemon=True).start()
    threading.Thread(target=_stats_loop, daemon=True).start()
    cps = round(1.0 / interval_s, 1) if interval_s > 0 else "MAX"
    _status(f"AKTIV  {interval_s*1000:.3f} ms  ({cps}/s)", C_GREEN)
    toggle_btn.config(text=f"STOPP  [{S['hk_stop'].upper()}]",
                      bg=C_RED, activebackground="#ff6b81")
    indicator.config(fg=C_GREEN)

def stop_clicking():
    S["running"] = False
    _lock(False)
    _status("Gestoppt", C_ORANGE)
    toggle_btn.config(text=f"START  [{S['hk_start'].upper()}]",
                      bg=C_GREEN, activebackground="#7bed9f")
    indicator.config(fg=C_RED)

def toggle_click():
    stop_clicking() if S["running"] else start_clicking()

def reset_stats():
    S["count"] = 0
    S["times"] = []
    _update_stats(0, 0)

def _lock(locked):
    st = "disabled" if locked else "normal"
    for w in _lockable:
        try: w.config(state=st)
        except: pass

def _status(txt, col):
    try: status_lbl.config(text=txt, fg=col)
    except: pass

def _update_stats(total, cps):
    try:
        lbl_total.config(text=f"{total:,}")
        lbl_cps.config(text=f"{cps}/s")
    except: pass

# ═══════════════════════════════════════════════════════════
# HOTKEYS
# ═══════════════════════════════════════════════════════════
def _unhook():
    try: keyboard.unhook_all()
    except: pass

def _register():
    _unhook()
    try: keyboard.add_hotkey(S["hk_start"], lambda: root.after(0, start_clicking))
    except: pass
    try: keyboard.add_hotkey(S["hk_stop"],  lambda: root.after(0, stop_clicking))
    except: pass

def _begin_record(which):
    """Oeffnet ein Popup-Fenster das auf Tastendruck wartet."""
    popup = tk.Toplevel(root)
    popup.title("Hotkey setzen")
    popup.geometry("320x160")
    popup.configure(bg=CARD)
    popup.resizable(False, False)
    popup.grab_set()
    popup.focus_force()
    popup.attributes("-topmost", True)

    label_which = "START" if which == "start" else "STOP"
    tk.Label(popup, text=f"Hotkey fuer {label_which} setzen",
             font=(FONT, 12, "bold"), fg=FG, bg=CARD).pack(pady=(20,8))
    tk.Label(popup, text="Druecke eine Taste ...",
             font=(FONT, 10), fg=MUTED, bg=CARD).pack()
    info_lbl = tk.Label(popup, text="ESC = Abbrechen",
                        font=(FONT, 8), fg="#3a3a55", bg=CARD)
    info_lbl.pack(pady=(6,0))

    def on_key(event):
        # tkinter keysym -> lesbarer Name
        key = event.keysym.lower()
        # F-Tasten: F1->f1, etc.
        if key.startswith("f") and key[1:].isdigit():
            key = key  # z.B. "f1"
        if key == "escape":
            popup.destroy()
            return
        # Sonderzeichen normalisieren
        key_map = {"control_l": "ctrl", "control_r": "ctrl",
                   "alt_l": "alt", "alt_r": "alt",
                   "shift_l": "shift", "shift_r": "shift",
                   "return": "enter", "space": "space"}
        key = key_map.get(key, key)

        popup.destroy()
        if which == "start":
            S["hk_start"] = key
            lbl_hk_start.config(text=key.upper())
            btn_rec_start.config(text=f"{key.upper()}  ✎", bg=ACCENT, fg=MUTED)
        else:
            S["hk_stop"] = key
            lbl_hk_stop.config(text=key.upper())
            btn_rec_stop.config(text=f"{key.upper()}  ✎", bg=ACCENT, fg=MUTED)
        _unhook()
        _register()
        _refresh_btn()

    popup.bind("<KeyPress>", on_key)

def _refresh_btn():
    if S["running"]:
        toggle_btn.config(text=f"STOPP  [{S['hk_stop'].upper()}]")
    else:
        toggle_btn.config(text=f"START  [{S['hk_start'].upper()}]")

def toggle_on_top():
    S["on_top"] = not S["on_top"]
    root.attributes("-topmost", S["on_top"])
    aot_btn.config(
        text="📌 Vordergrund AN" if S["on_top"] else "📌 Vordergrund AUS",
        fg=C_GREEN if S["on_top"] else MUTED,
    )

# ═══════════════════════════════════════════════════════════
# GUI
# ═══════════════════════════════════════════════════════════
root = tk.Tk()
root.title("AutoClicker v5")
root.geometry("440x640")
root.resizable(False, False)

BG    = "#0d0d14"
PANEL = "#13131f"
CARD  = "#1a1a2e"
ACCENT= "#1e2240"
C_GREEN  = "#2ed573"
C_RED    = "#ff4757"
C_ORANGE = "#ffa502"
C_PURPLE = "#7c4dff"
FG    = "#e8e8f0"
MUTED = "#5a5a78"
FONT  = "Consolas"

root.configure(bg=BG)
_lockable = []  # Widgets die beim Klicken gesperrt werden

def _card(pady=12, padx=16):
    f = tk.Frame(root, bg=CARD, padx=padx, pady=pady)
    f.pack(padx=14, fill="x", pady=(0, 6))
    return f

def _lbl(p, txt, sz=9, bold=False, col=None):
    return tk.Label(p, text=txt, font=(FONT, sz, "bold" if bold else ""),
                    fg=col or MUTED, bg=p.cget("bg"))

def _gap(h=6):
    tk.Frame(root, bg=BG, height=h).pack()

# ─── HEADER ──────────────────────────────────────────────
hdr = tk.Frame(root, bg=PANEL, pady=10)
hdr.pack(fill="x")
indicator = tk.Label(hdr, text="●", font=(FONT, 17), fg=C_RED, bg=PANEL)
indicator.pack(side="left", padx=(16, 5))
tk.Label(hdr, text="AUTO CLICKER  v5", font=(FONT, 17, "bold"), fg=FG, bg=PANEL).pack(side="left")
aot_btn = tk.Button(hdr, text="📌 Vordergrund AUS",
                    font=(FONT, 8), fg=MUTED, bg=PANEL,
                    relief="flat", bd=0, cursor="hand2",
                    activebackground=ACCENT, activeforeground=FG,
                    padx=6, pady=3, command=toggle_on_top)
aot_btn.pack(side="right", padx=10)
_gap(4)

# ─── INTERVAL ────────────────────────────────────────────
c1 = _card(pady=10)
_lbl(c1, "KLICK-INTERVAL", sz=9, bold=True).pack(anchor="w")
tk.Frame(c1, bg=CARD, height=4).pack()

row_iv = tk.Frame(c1, bg=CARD)
row_iv.pack(fill="x")
iv = tk.StringVar(value="100")
e_ms = tk.Entry(row_iv, textvariable=iv, font=(FONT, 26, "bold"),
                fg=FG, bg=ACCENT, insertbackground=C_GREEN,
                relief="flat", width=7, justify="center", bd=0)
e_ms.pack(side="left", ipady=5, padx=(0, 8))
_lockable.append(e_ms)
tk.Label(row_iv, text="ms", font=(FONT, 13, "bold"), fg=MUTED, bg=CARD).pack(side="left")

# Presets
prow = tk.Frame(c1, bg=CARD)
prow.pack(anchor="w", pady=(10, 0))
_lbl(prow, "Presets:").pack(side="left", padx=(0, 5))
for lbl_t, val in [("0.004","0.004"),("1","1"),("10","10"),("50","50"),
                   ("100","100"),("250","250"),("500","500"),("1000","1000")]:
    b = tk.Button(prow, text=lbl_t, font=(FONT, 8, "bold"),
                  fg=MUTED, bg=ACCENT, relief="flat", bd=0,
                  activebackground=PANEL, activeforeground=FG,
                  command=lambda v=val: iv.set(v),
                  cursor="hand2", padx=5, pady=2)
    b.pack(side="left", padx=2)
    _lockable.append(b)
_lbl(c1, "0.004 ms = maximale Geschwindigkeit (CPU-limitiert)", sz=7, col="#2d2d45").pack(anchor="w", pady=(5,0))
_gap(3)

# ─── AUTO-STOP + DELAY ───────────────────────────────────
c2 = _card(pady=10)
row_opts = tk.Frame(c2, bg=CARD)
row_opts.pack(fill="x")

def _opt_block(parent, title, default, unit, tip):
    f = tk.Frame(parent, bg=CARD)
    f.pack(side="left", expand=True, fill="x", padx=(0,10))
    _lbl(f, title, sz=8, bold=True).pack(anchor="w")
    tk.Frame(f, bg=CARD, height=3).pack()
    v = tk.StringVar(value=default)
    e = tk.Entry(f, textvariable=v, font=(FONT, 18, "bold"),
                 fg=FG, bg=ACCENT, insertbackground=C_GREEN,
                 relief="flat", width=6, justify="center", bd=0)
    e.pack(ipady=5, fill="x")
    _lbl(f, f"{unit}  {tip}", sz=7, col="#2d2d45").pack(anchor="w", pady=(3,0))
    _lockable.append(e)
    return v

autostop_v = _opt_block(row_opts, "AUTO-STOP",   "0", "Sekunden", "(0 = aus)")
delay_v    = _opt_block(row_opts, "START-DELAY", "0", "Sekunden", "(0 = sofort)")
_gap(3)

# ─── LIVE STATISTIK ──────────────────────────────────────
c3 = _card(pady=10)
st_row = tk.Frame(c3, bg=CARD)
st_row.pack(fill="x")

sl = tk.Frame(st_row, bg=CARD)
sl.pack(side="left", expand=True)
_lbl(sl, "GESAMT-KLICKS", sz=8, bold=True).pack()
lbl_total = tk.Label(sl, text="0", font=(FONT, 22, "bold"), fg=C_GREEN, bg=CARD)
lbl_total.pack()

tk.Frame(st_row, bg=ACCENT, width=2).pack(side="left", fill="y", padx=10)

sr = tk.Frame(st_row, bg=CARD)
sr.pack(side="left", expand=True)
_lbl(sr, "KLICKS/SEK (live)", sz=8, bold=True).pack()
lbl_cps = tk.Label(sr, text="0/s", font=(FONT, 22, "bold"), fg=C_ORANGE, bg=CARD)
lbl_cps.pack()

tk.Button(c3, text="↺  Zaehler zuruecksetzen",
          font=(FONT, 8), fg=MUTED, bg=ACCENT,
          relief="flat", bd=0, cursor="hand2",
          activebackground=PANEL, activeforeground=FG,
          padx=8, pady=5, command=reset_stats).pack(fill="x", pady=(8,0))
_gap(3)

# ─── HOTKEYS ─────────────────────────────────────────────
c4 = _card(pady=10)
_lbl(c4, "HOTKEYS", sz=9, bold=True, col=FG).pack(anchor="w")
tk.Frame(c4, bg=CARD, height=8).pack()

hk_row = tk.Frame(c4, bg=CARD)
hk_row.pack(fill="x")

# Start-Hotkey
hl = tk.Frame(hk_row, bg=CARD)
hl.pack(side="left", expand=True, fill="x", padx=(0,6))
_lbl(hl, "STARTEN", sz=8).pack()
lbl_hk_start = tk.Label(hl, text="F1", font=(FONT, 16, "bold"), fg=C_GREEN, bg=CARD)
lbl_hk_start.pack(pady=(2,3))
btn_rec_start = tk.Button(hl, text="✎  Taste aendern",
                           font=(FONT, 10, "bold"), fg="white", bg="#2255aa",
                           relief="flat", bd=0, cursor="hand2",
                           activebackground="#3377cc", activeforeground="white",
                           padx=10, pady=6,
                           command=lambda: _begin_record("start"))
btn_rec_start.pack(fill="x")

tk.Frame(hk_row, bg=ACCENT, width=2).pack(side="left", fill="y", padx=8)

# Stop-Hotkey
hr = tk.Frame(hk_row, bg=CARD)
hr.pack(side="left", expand=True, fill="x", padx=(6,0))
_lbl(hr, "STOPPEN", sz=8).pack()
lbl_hk_stop = tk.Label(hr, text="F2", font=(FONT, 16, "bold"), fg=C_RED, bg=CARD)
lbl_hk_stop.pack(pady=(2,3))
btn_rec_stop = tk.Button(hr, text="✎  Taste aendern",
                          font=(FONT, 10, "bold"), fg="white", bg="#aa2233",
                          relief="flat", bd=0, cursor="hand2",
                          activebackground="#cc3344", activeforeground="white",
                          padx=10, pady=6,
                          command=lambda: _begin_record("stop"))
btn_rec_stop.pack(fill="x")

tk.Frame(c4, bg=CARD, height=8).pack()
_lbl(c4, "Klicke den Button → Popup oeffnet sich → Taste druecken  |  ESC = Abbrechen",
     sz=8, col="#4a4a6a").pack(anchor="center")
_gap(3)

# ─── STATUS + HAUPT-BUTTON ───────────────────────────────
status_lbl = tk.Label(root, text="Gestoppt",
                       font=(FONT, 11, "bold"), fg=C_ORANGE, bg=BG)
status_lbl.pack()
_gap(4)

toggle_btn = tk.Button(root, text="START  [F1]",
                       font=(FONT, 15, "bold"),
                       fg="white", bg=C_GREEN,
                       activeforeground="white", activebackground="#7bed9f",
                       relief="flat", bd=0, cursor="hand2",
                       padx=30, pady=11, command=toggle_click)
toggle_btn.pack(padx=14, fill="x")
_gap(5)

tk.Button(root, text="💾  Einstellungen speichern",
          font=(FONT, 9, "bold"), fg="white", bg=C_PURPLE,
          activeforeground="white", activebackground="#9c6fff",
          relief="flat", bd=0, cursor="hand2",
          padx=12, pady=6, command=_save_cfg).pack(padx=14, fill="x")
_gap(5)
tk.Label(root, text="Klickt an der aktuellen Mausposition  |  Funktioniert auch minimiert",
         font=(FONT, 7), fg="#222233", bg=BG).pack()

# ═══════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════
cfg = _load_cfg()
iv.set(cfg["interval_ms"])
S["hk_start"] = cfg["hotkey_start"]
S["hk_stop"]  = cfg["hotkey_stop"]
autostop_v.set(cfg["auto_stop_sec"])
delay_v.set(cfg["delay_sec"])

lbl_hk_start.config(text=S["hk_start"].upper())
lbl_hk_stop.config(text=S["hk_stop"].upper())
btn_rec_start.config(text=f"{S['hk_start'].upper()}  ✎")
btn_rec_stop.config(text=f"{S['hk_stop'].upper()}  ✎")
_refresh_btn()

if cfg["always_on_top"]:
    toggle_on_top()

_register()

def _on_close():
    S["running"] = False
    _unhook()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", _on_close)
root.mainloop()