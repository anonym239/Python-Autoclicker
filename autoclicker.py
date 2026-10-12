"""
AutoClicker 6
=============

Starten:  python autoclicker.py         (oder Starten.bat doppelklicken)
Demo:     python autoclicker.py --demo  (simuliert Klicks, läuft überall)

Keine Zusatzmodule nötig – Python 3.9+ unter Windows 10/11.
Fertige Windows-Version mit Installer: siehe Releases auf GitHub.
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
