# AutoClicker

Ein einfacher, schneller Autoclicker für Windows 10/11 (nur PC) – mit Modus für Minecraft-PvP und CPS-Boost.

## Installieren

1. Rechts auf GitHub unter **Releases** die neueste Version öffnen.
2. **`AutoClicker-Setup-….exe`** herunterladen und starten.
3. Fertig – „AutoClicker“ steht jetzt im Startmenü (auf Wunsch auch auf dem Desktop).

> Windows zeigt bei neuen Programmen manchmal „Der Computer wurde durch Windows geschützt“.
> Dann auf **Weitere Informationen → Trotzdem ausführen** klicken.

Ohne Installation: `AutoClicker-…-portable.zip` entpacken und `AutoClicker.exe` starten.

## So geht's

1. **Links einen Modus wählen.**
2. **Tempo einstellen** (Klicks pro Sekunde).
3. **F6 drücken** – auch mitten im Spiel. Es wird sofort geklickt, nochmal F6 = Stopp.

| Modus | Was passiert |
| --- | --- |
| Standard | F6 an, F6 aus – klickt mit dem eingestellten Tempo |
| Minecraft PvP | F6 an, dann Maustaste **halten** = schnelle Klicks |
| CPS-Boost | F6 an, dann normal klicken – **jeder Klick zählt doppelt** (oder dreifach) |
| AFK-Farm | Klickt langsam weiter (1,6 CPS = Schwert-Cooldown) |

Unter **Hotkeys bearbeiten** legst du eigene Tasten an – jeweils für An/Aus, nur An oder nur Aus
(auch Kombinationen wie Strg+R oder die Maus-Seitentasten). Weitere Optionen (Auto-Stopp,
nur in Minecraft klicken, Hell/Dunkel) findest du unter **Einstellungen**.

Viele Server verbieten Autoclicker – nutze ihn dort, wo es erlaubt ist.

## Für Entwickler

- Aus dem Quellcode starten: `python autoclicker.py` (Python 3.9+, keine Zusatzmodule)
- Tests: `python -m unittest discover -s tests -t .`
- EXE + Installer bauen (Windows): `pip install pyinstaller`, Inno Setup 6 installieren,
  dann `python tools/build_windows.py`

**Neues Release mit .exe:** Auf GitHub unter *Releases → Draft a new release* einen Tag wie
`v6.1.0` anlegen und veröffentlichen. Der Workflow *Windows-Build* baut dann automatisch
Setup und ZIP und hängt beides an das Release.
