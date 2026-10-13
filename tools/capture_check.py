"""Prueft die Bildschirmaufnahme unter Windows (DXGI + GDI). Nur zur Info im Build.

    python tools/capture_check.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clicker.dxgi_capture import DesktopDuplication  # noqa: E402
from clicker.platform_win import WindowsBackend  # noqa: E402


def main() -> int:
    WindowsBackend()  # setzt DPI-Bewusstsein
    dup = DesktopDuplication()
    for i in range(3):
        t = time.perf_counter()
        data = dup.grab(0, 0, 320, 64)
        ms = (time.perf_counter() - t) * 1000
        print(f"DXGI {i}: {'%d Bytes' % len(data) if data else 'nichts'} in {ms:.1f} ms {dup.error}")
    backend = WindowsBackend()
    data = backend._blit(None, 0, 0, 320, 64)
    print(f"GDI: {'%d Bytes' % len(data) if data else 'nichts'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
