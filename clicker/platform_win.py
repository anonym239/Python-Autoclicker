"""Windows-Anbindung ueber ctypes – keine Zusatzmodule noetig.

- Klicks per SendInput (Down+Up in einem Aufruf, markiert mit MAGIC, damit
  der eigene Hook sie erkennt und ignoriert).
- Globale Hotkeys + Maustasten ueber Low-Level-Hooks (WH_KEYBOARD_LL /
  WH_MOUSE_LL). Der Maus-Hook wird nur installiert, wenn er gebraucht wird,
  damit die Maus im Spiel nie verzoegert wird.
- Vordergrundfenster, Timer-Aufloesung, Sounds, "Immer im Vordergrund".
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes as wt

from .keys import vk_to_name

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    winmm = ctypes.WinDLL("winmm")
except OSError:  # sehr selten, nur fuer Timer-Aufloesung
    winmm = None

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
MAGIC = 0x41435636  # "ACV6" – Kennung unserer eigenen Klicks

# ─── Strukturen ────────────────────────────────────────────
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

# ─── Signaturen (wichtig auf 64 Bit!) ──────────────────────
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD

# ─── Konstanten ────────────────────────────────────────────
INPUT_MOUSE = 0
BUTTON_FLAGS = {  # (down, up)
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT, WM_APP = 0x0012, 0x8000
WM_SET_MOUSE_HOOK = WM_APP + 1
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
MOUSE_MSGS = {
    0x0201: ("left", True), 0x0202: ("left", False),
    0x0204: ("right", True), 0x0205: ("right", False),
    0x0207: ("middle", True), 0x0208: ("middle", False),
    0x020B: ("x", True), 0x020C: ("x", False),
}
LLMHF_INJECTED = 0x01
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SW_RESTORE = 9

SOUNDS = {
    "start": ((880, 60), (1320, 90)),
    "stop": ((660, 60), (440, 110)),
    "limit": ((523, 70), (659, 70), (784, 120)),
}


def _make_inputs(*flags: int):
    arr = (INPUT * len(flags))()
    for i, f in enumerate(flags):
        arr[i].type = INPUT_MOUSE
        arr[i].u.mi = MOUSEINPUT(0, 0, 0, f, 0, MAGIC)
    return arr


def _window_text(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


class _HookThread(threading.Thread):
    """Besitzt die Low-Level-Hooks und deren Nachrichtenschleife.

    Die Callbacks machen absichtlich fast nichts (nur in eine Queue legen),
    weil Windows Hooks entfernt, die zu lange brauchen."""

    def __init__(self, sink: queue.Queue):
        super().__init__(name="input-hooks", daemon=True)
        self._sink = sink
        self._kb_proc = HOOKPROC(self._kb_callback)
        self._ms_proc = HOOKPROC(self._ms_callback)
        self._kb_hook = None
        self._ms_hook = None
        self._tid = 0
        self.want_mouse = False
        self.ready = threading.Event()
        self.ok = False

    # Callbacks -------------------------------------------------
    def _kb_callback(self, n_code, w_param, l_param):
        if n_code == 0:
            try:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._sink.put_nowait(("k", vk_to_name(kb.vkCode), True))
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    self._sink.put_nowait(("k", vk_to_name(kb.vkCode), False))
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _ms_callback(self, n_code, w_param, l_param):
        if n_code == 0 and w_param != WM_MOUSEMOVE:
            info = MOUSE_MSGS.get(w_param)
            if info is not None:
                try:
                    ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    own = (ms.flags & LLMHF_INJECTED) and ms.dwExtraInfo == MAGIC
                    if not own:
                        button, down = info
                        if button == "x":
                            button = "x1" if (ms.mouseData >> 16) & 0xFFFF == 1 else "x2"
                        self._sink.put_nowait(("m", button, down))
                except Exception:
                    pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    # Schleife --------------------------------------------------
    def _set_mouse(self, on: bool, hmod) -> None:
        if on and not self._ms_hook:
            self._ms_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, hmod, 0)
        elif not on and self._ms_hook:
            user32.UnhookWindowsHookEx(self._ms_hook)
            self._ms_hook = None

    def run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        # Nachrichtenwarteschlange anlegen, bevor andere Threads posten
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        hmod = kernel32.GetModuleHandleW(None)
        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, hmod, 0)
        self.ok = bool(self._kb_hook)
        self._set_mouse(self.want_mouse, hmod)
        self.ready.set()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == WM_SET_MOUSE_HOOK:
                self._set_mouse(bool(msg.wParam), hmod)
        self._set_mouse(False, hmod)
        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None

    def post(self, message: int, w_param: int = 0) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, message, w_param, 0)


class WindowsBackend:
    name = "windows"
    has_global_input = True

    def __init__(self):
        self._both = {b: _make_inputs(*f) for b, f in BUTTON_FLAGS.items()}
        self._size = ctypes.sizeof(INPUT)
        self._timer_high = False
        self._hooks: _HookThread | None = None
        self._want_mouse = False
        self._events: queue.Queue = queue.Queue()
        self._dispatcher: threading.Thread | None = None
        self._sound_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._sound_worker, name="sound", daemon=True).start()

    def claim_instance(self) -> None:
        """Benannter Mutex: der Installer erkennt so ein laufendes Programm."""
        self._mutex = kernel32.CreateMutexW(None, False, "AutoClicker6.Running")

    # ─── Klicks ──────────────────────────────────────────
    def click(self, button: str) -> None:
        """Druecken + Loslassen in einem SendInput-Aufruf."""
        user32.SendInput(2, self._both[button], self._size)

    # ─── Fenster ─────────────────────────────────────────
    def foreground_title(self) -> str:
        hwnd = user32.GetForegroundWindow()
        return _window_text(hwnd) if hwnd else ""

    def _find_windows(self, title_part: str):
        found = []
        needle = title_part.lower()

        def cb(hwnd, _lp):
            if user32.IsWindowVisible(hwnd) and needle in _window_text(hwnd).lower():
                if _class_name(hwnd).startswith("Chrome_WidgetWin"):
                    found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return found

    def set_topmost(self, title_part: str, on: bool) -> bool:
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        after = HWND_TOPMOST if on else HWND_NOTOPMOST
        hits = self._find_windows(title_part)
        for hwnd in hits:
            user32.SetWindowPos(hwnd, after, 0, 0, 0, 0, flags)
        return bool(hits)

    def focus_window(self, title_part: str) -> bool:
        hits = self._find_windows(title_part)
        for hwnd in hits[:1]:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        return bool(hits)

    # ─── Timer / Sound ───────────────────────────────────
    def set_timer_resolution(self, high: bool) -> None:
        if winmm is None or high == self._timer_high:
            return
        (winmm.timeBeginPeriod if high else winmm.timeEndPeriod)(1)
        self._timer_high = high

    def beep(self, kind: str) -> None:
        self._sound_q.put(kind)

    def _sound_worker(self) -> None:
        import winsound
        while True:
            kind = self._sound_q.get()
            for freq, ms in SOUNDS.get(kind, ()):
                try:
                    winsound.Beep(freq, ms)
                except RuntimeError:
                    break

    # ─── Hooks ───────────────────────────────────────────
    def start_input(self, matcher) -> None:
        if self._hooks:
            return
        self._hooks = _HookThread(self._events)
        self._hooks.want_mouse = self._want_mouse
        self._hooks.start()
        self._hooks.ready.wait(3)
        self._dispatcher = threading.Thread(target=self._dispatch, args=(matcher,),
                                            name="input-dispatch", daemon=True)
        self._dispatcher.start()

    @property
    def hooks_ok(self) -> bool:
        return bool(self._hooks and self._hooks.ok)

    def set_mouse_hook(self, needed: bool) -> None:
        self._want_mouse = needed
        if self._hooks and self._hooks.want_mouse != needed:
            self._hooks.want_mouse = needed
            self._hooks.post(WM_SET_MOUSE_HOOK, int(needed))

    def stop_input(self) -> None:
        if self._hooks:
            self._hooks.post(WM_QUIT)
            self._hooks.join(2)
            self._hooks = None
        self._events.put(None)

    def _dispatch(self, matcher) -> None:
        while True:
            item = self._events.get()
            if item is None:
                return
            kind, name, down = item
            try:
                if kind == "k":
                    matcher.key_event(name, down)
                else:
                    matcher.mouse_event(name, down)
            except Exception:
                pass

