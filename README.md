# AutoClicker v6 – Block Edition

Ein schneller, präziser Autoclicker für Windows mit moderner Oberfläche im Minecraft-Look,
Minecraft-Profilen und einer Handy-Fernbedienung per QR-Code.

**Keine Zusatzmodule nötig.** Nur Python 3.9+ unter Windows 10/11 – kein `pip install`.

## Starten

1. Python installieren: <https://www.python.org/downloads/> (beim Installieren den Haken bei
   **„Add python.exe to PATH“** setzen).
2. Dieses Repo herunterladen (grüner Knopf **Code → Download ZIP**) und entpacken.
3. **`Starten.bat`** doppelklicken.
   Ohne Konsolenfenster: **`AutoClicker.pyw`** doppelklicken.

Die Oberfläche öffnet sich als eigenes Fenster (Microsoft Edge im App-Modus, ist auf jedem
Windows dabei). Fenster schließen = Programm beenden.

```text
python autoclicker.py            normal starten
python autoclicker.py --demo     Demo: Klicks werden nur simuliert (läuft auch ohne Windows)
python autoclicker.py --browser  im Standardbrowser statt als App-Fenster öffnen
python autoclicker.py --remote   Handy-Fernbedienung direkt einschalten
python autoclicker.py --port 9000
```

## Was kann v6?

| Bereich | Funktionen |
| --- | --- |
| Klicken | Links / Mitte / Rechts, 0,1 bis 1000 CPS, CPS-Bereich mit zufälliger Variation, Eingabe in CPS oder ms |
| Modi | **Umschalten** (Hotkey an/aus), **Maus halten** (an + Maustaste halten = Autoklick), **Taste halten** (klickt, solange der Hotkey gedrückt ist) |
| Dauerdrücken | Hält die Taste fest – für AFK-Angeln, Cobblestone-Generator, Essen |
| Profile | PvP 1.8, PvP 1.9+, Bridging, AFK Mob-Farm, AFK Angeln, Cobble-Miner – eigene anlegen, umbenennen, duplizieren. Profilwechsel per Hotkey |
| Hotkeys | Global (auch im Spiel), Kombis wie `Strg+R`, Maus-Seitentasten 4/5, extra Not-Aus-Taste. Ein einfacher Hotkey löst auch aus, während du sprintest (Strg) |
| Smart | **Nur in Minecraft klicken** (pausiert, sobald ein anderes Fenster vorne ist), **Pause in Inventar & Chat** (Beta), klickt nie ins eigene Fenster |
| Sicherheit | Auto-Stopp nach Zeit oder Klicks, Start-Countdown, Start per Knopf/Handy wartet immer 3 s |
| Anzeige | Live-CPS, CPS-Graph der letzten 30 s, Rekord, Laufzeit, Gesamtklicks als Minecraft-XP-Level |
| Extras | Sounds bei Start/Stopp/Countdown, immer im Vordergrund, 5 Farben (Gras, Diamant, Redstone, Amethyst, Gold) |
| Handy | Fernbedienung im Browser: QR-Code scannen, Start/Stopp, Profile, Live-CPS. Lässt sich als App auf den Startbildschirm legen |

### Bessere Logik als v5

- **Genaues Timing:** feste Zeitplanung statt `sleep` nach jedem Klick – kein Verzögern, kein
  Hinterherhinken. Nur die letzten ~2 ms werden genau abgewartet, deshalb bleibt die CPU-Last gering.
- **Klick in einem Rutsch:** Drücken + Loslassen in einem `SendInput`-Aufruf.
- **Eigene Klicks werden erkannt** und nie mit echten Mausklicks verwechselt.
- **Kein Selbst-Stopp mehr:** v5 klickte nach dem Start-Knopf direkt auf den eigenen Stopp-Knopf.
  v6 wartet 3 s und klickt nie ins eigene Fenster.
- **Keine Abhängigkeiten:** Das Modul `keyboard` wird nicht mehr gebraucht. Hotkeys laufen über
  Windows-Hooks direkt per `ctypes`. Der Maus-Hook ist nur aktiv, wenn er gebraucht wird – die
  Maus im Spiel wird nie verzögert.
- **Einstellungen aus v5** (Intervall, Hotkeys) werden beim ersten Start automatisch als
  Profil „Mein v5“ übernommen.

## Handy-Fernbedienung

1. Am PC im Tab **Handy** die Fernbedienung einschalten.
2. Handy ins **gleiche WLAN** wie den PC.
3. QR-Code scannen. Fragt Windows nach der Firewall: **Zugriff zulassen** (privates Netzwerk).
4. Optional im Handy-Browser „Zum Startbildschirm hinzufügen“.

Die Adresse enthält einen geheimen Code – ohne ihn kann niemand im WLAN deine Maus steuern.
Mit **Neuen Code erzeugen** sperrst du alte Geräte aus.

## Minecraft-Tipps

| Profil | Einstellung | Wofür |
| --- | --- | --- |
| PvP 1.8 | Links, Maus halten, 10–14 CPS | Klassisches 1.8-PvP |
| PvP 1.9+ | Links, Maus halten, 1,6 CPS | Schwert-Cooldown (625 ms) voll ausnutzen |
| Bridging | Rechts, Maus halten, 9–12 CPS | Blöcke setzen |
| AFK Mob-Farm | Links, Umschalten, 1,6 CPS | Mob-Farm mit Schwert-Sweep |
| AFK Angeln | Rechts, Dauerdrücken | AFK-Fischfarm |
| Cobble-Miner | Links, Dauerdrücken | Cobblestone-Generator abbauen |

> Viele Server verbieten Autoclicker. Nutze ihn dort, wo es erlaubt ist – Singleplayer,
> eigene Server, AFK-Farmen.

## Probleme?

- **Hotkeys gehen im Spiel nicht:** Läuft Minecraft (oder der Launcher) als Administrator,
  muss der AutoClicker auch als Administrator laufen.
- **Kein Fenster erscheint:** `python autoclicker.py --browser` öffnet die Oberfläche im Standardbrowser.
- **Handy findet den PC nicht:** gleiches WLAN? Firewall-Abfrage erlaubt? Gast-WLANs blockieren
  oft Geräte untereinander.
- **„Nur in Minecraft“ pausiert immer:** Im Tab Smart den Fensternamen deines Clients ergänzen
  (z. B. `Lunar Client`).
- Einstellungen liegen in `clicker_settings.json` neben dem Programm. Löschen = Werkseinstellungen.

## Für Entwickler

```text
autoclicker.py          Einstieg
AutoClicker.pyw         Start ohne Konsole
clicker/engine.py       Klick-Engine (Timing, Modi, Statistik)
clicker/keys.py         Hotkey-Erkennung und -Aufnahme
clicker/platform_win.py Windows-API per ctypes (SendInput, Hooks, Fenster)
clicker/config.py       Einstellungen, Profile, Migration von v5
clicker/server.py       HTTP-API + Web-Oberfläche (nur Standardbibliothek)
clicker/app.py          verbindet alles, öffnet das Fenster
web/                    Oberfläche (HTML/CSS/JS, Schriften)
tools/build_preview.py  baut eine einzelne Vorschau-HTML mit simuliertem Programm
tests/                  Tests (test_windows.py läuft nur unter Windows)
```

Tests: `python -m unittest discover -s tests -t .`

## Lizenzen von Drittanbietern

- Schriften *Chakra Petch* und *Jersey 15*: SIL Open Font License (`web/fonts/OFL-*.txt`)
- QR-Code-Generator von Project Nayuki: MIT-Lizenz (`clicker/qrcodegen.py`)
