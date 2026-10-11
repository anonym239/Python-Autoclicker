"""
AutoClicker v6 – Block Edition
==============================

Starten:   python autoclicker.py        (oder Starten.bat doppelklicken)
Demo:      python autoclicker.py --demo (simuliert Klicks, laeuft ueberall)

Keine Zusatzmodule noetig – nur Python 3.9+ unter Windows 10/11.
Die Oberflaeche oeffnet sich als eigenes Fenster (Microsoft Edge App-Modus).

Features:
  - CPS-Bereich mit natuerlicher Variation, Links/Rechts/Mitte
  - Modi: Umschalten, Maus halten (PvP), Taste halten
  - Dauerdruecken fuer AFK-Farmen (Angeln, Cobblestone)
  - Minecraft-Profile, Profil-Wechsel per Hotkey
  - Nur in Minecraft klicken, Pause im Inventar/Chat
  - Auto-Stopp (Zeit/Klicks), Start-Countdown, Sounds
  - Live-CPS-Graph, Statistik, Level
  - Handy-Fernbedienung per QR-Code (gleiches WLAN)
"""

import os
import sys

if sys.version_info < (3, 9):
    print("Bitte Python 3.9 oder neuer installieren: https://www.python.org/downloads/")
    input("Enter zum Beenden...")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clicker.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
