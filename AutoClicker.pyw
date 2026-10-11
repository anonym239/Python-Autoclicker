"""Doppelklick-Start ohne Konsolenfenster (Windows: .pyw laeuft mit pythonw)."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _message(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "AutoClicker v6", 0x10)
    except Exception:
        pass


try:
    from clicker.app import main
    code = main()
    if code:
        _message("Der AutoClicker konnte nicht starten.\n\n"
                 "Starte Starten.bat, dort steht der genaue Grund.")
except Exception:
    _message("Unerwarteter Fehler:\n\n" + traceback.format_exc()[-1500:])
