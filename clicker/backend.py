"""Backend-Auswahl: echtes Windows oder Demo-Modus (Vorschau/Tests)."""

from __future__ import annotations

import sys
import threading
import time


class DemoBackend:
    """Simuliert Klicks und Fenster. Wird auf Nicht-Windows-Systemen und mit
    --demo benutzt, damit die Oberflaeche ueberall ausprobiert werden kann."""

    name = "demo"
    has_global_input = False

    def __init__(self):
        self.clicks = 0
        self.down: set[str] = set()
        self.foreground = "Minecraft 1.21.4 (Demo)"
        self.captured = True
        self.beeps: list[str] = []
        self.timer_high = False
        self._lock = threading.Lock()

    def click(self, button: str, hold_s: float = 0.0) -> None:
        if hold_s > 0:
            time.sleep(hold_s)
        with self._lock:
            self.clicks += 1

    def press(self, button: str) -> None:
        self.down.add(button)

    def release(self, button: str) -> None:
        self.down.discard(button)

    def foreground_title(self) -> str:
        return self.foreground

    def mouse_captured(self) -> bool | None:
        return self.captured

    def set_timer_resolution(self, high: bool) -> None:
        self.timer_high = high

    def beep(self, kind: str) -> None:
        self.beeps.append(kind)

    def set_topmost(self, title_part: str, on: bool) -> bool:
        return False

    def focus_window(self, title_part: str) -> bool:
        return False

    def claim_instance(self) -> None:
        pass

    def start_input(self, matcher) -> None:
        pass

    def set_mouse_hook(self, needed: bool) -> None:
        pass

    def stop_input(self) -> None:
        pass


def create_backend(force_demo: bool = False):
    if not force_demo and sys.platform == "win32":
        from .platform_win import WindowsBackend
        return WindowsBackend()
    return DemoBackend()
