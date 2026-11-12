# Arbeitsplan: RE2 Remake Koop

## Ziel und Stand

Ziel ist eine eigenständige Zwei-Spieler-Mod mit nachweislich gemeinsamem Spielzustand über die gesamte Kampagne. Der vorhandene Python-Code ist ein Netzwerk- und Zustandsprototyp. Die REFramework-Probe hat Zugriff auf Spieler-Transform und Inventar-Typ in RE2 TDB 70 bestätigt. Eine spielbare Mod existiert noch nicht. [STATUS.md](STATUS.md) führt alle offenen Anforderungen und Nachweise auf.

Eine veröffentlichte Fremdmod dient nur als Vergleich; ihre Dateien oder Assets werden wegen der veröffentlichten Änderungsrechte nicht übernommen.

## Arbeitspakete und Zuständigkeiten

Die Rollen bezeichnen Verantwortungsbereiche. Namen werden erst eingetragen, wenn Mitwirkende sie übernehmen. Jede Rolle besitzt ihren Ordner und liefert dokumentierte Schnittstellen, Beispielnachrichten und einen reproduzierbaren Test.

| Rolle | Verzeichnis | Aufgabe | Übergabe an Integration |
|---|---|---|---|
| Integration und Architektur | `protocol/`, Projektkonfiguration | Gemeinsames Nachrichtenschema, Sitzungskennung, Sequenz, Zustandsprüfung, Versionsabgleich, Review und Release | Versioniertes Schema und Kompatibilitätstest für jedes Paket |
| RE2-Spieler und Kampf | `game/player/`, `game/combat/` | REFramework-Hooks für Position, Rotation, Aktionen, Schaden, Gegner-IDs, KI-Zustand und Tod; Ereignisse anwenden ohne Echo-Schleife | Zwei Spielinstanzen zeigen dieselben Spieler- und Kampfereignisse |
| Welt und Inventar | `game/world/` | Stabile IDs für Gegenstände, Türen, Rätsel, Inventar und Fortschrittsflags; Konflikte bei gleichzeitiger Interaktion behandeln | Snapshot und Ereignisstrom für jede Weltkategorie |
| Skripte und Zwischensequenzen | `game/story/` | Kampagnenereignisse und jede Cutscene kartieren; Start, Zeit, Skip und Ende koordinieren | Szenenmatrix mit Tests für beide Rollen |
| Lobby und Steam | `network/`, `ui/` | Steam-Freundeseinladung, Lobbybeitritt, Status, Bereitschaft, Originalmenü-Stil, Transport und Verbindungsfehler | Zwei Konten verbinden sich über Steam; Host startet erst bei kompatiblen Einstellungen |
| Speichern und Wiederherstellung | `save/` | Host-Spielstand, Slotwahl, atomare Checkpoints, Laden, Wiederverbindung und Abgleich nach Unterbrechung | Rejoin während Kampf, Rätsel und Cutscene ohne Zustandsabweichung |
| Qualitätssicherung | `tests/`, `docs/` | Zwei-Instanzen-Testplan, Messprotokolle, Kompatibilitätsmatrix, Regressionen und Einschränkungen | Nachweis für jede Zeile in [STATUS.md](STATUS.md) |

## Gemeinsame Schnittstelle

Ein Spielmodul meldet ein typisiertes Ereignis mit stabiler Objekt-ID und lokaler Beobachtungszeit an den Host. Nur der Host vergibt Sitzungskennung, Sequenz und verbindlichen Zustand. Clients wenden Ereignisse in dieser Reihenfolge an und prüfen den Zustandswert. Bei Lücke oder Abweichung fordern sie einen Snapshot an. Gameplay-Module dürfen keine eigenen Netzwerkformate oder separaten Spielstände definieren. Das Schema wird vor den Engine-Hooks versioniert; inkompatible Versionen dürfen nicht gemeinsam starten.

## Reihenfolge der Integration

1. **M0 – Reproduzierbare Basis:** Unterstützten RE2-Build und REFramework-Version festlegen, Probe im Spiel validieren, CI für Protokolltests aufsetzen.
2. **M1 – Zwei Spieler:** Eigenständige Engine-Bridge und Steam-Lobby. Bewegung, Rotation und Aktionen in beiden Instanzen sichtbar.
3. **M2 – Gemeinsame Welt:** Gegner, Schaden, Tod, Gegenstände, Inventar, Türen und Rätsel einschließlich gleichzeitiger Interaktion.
4. **M3 – Kampagne:** Fortschrittsflags, Skriptereignisse und alle Cutscenes mit Szenenmatrix.
5. **M4 – Fortsetzen:** Host-Spielstand, Slotwahl, Unterbrechung und Wiederverbindung in kritischen Szenen.
6. **M5 – Freigabe:** Vollständiger Zwei-Instanzen-Durchlauf, dokumentierte Einschränkungen, Installations- und Bedienanleitung.

Ein Meilenstein gilt erst mit einem Test in zwei echten RE2-Instanzen als abgeschlossen. Python-Protokolltests sind nur Vorprüfungen.

## Zusammenführung

- Ein Branch pro Aufgabe, Pull Request gegen `main`, Review durch Integration und mindestens eine betroffene Fachrolle.
- Änderungen am Nachrichtenschema zuerst als eigener Pull Request mit Migration und Testvektoren; Gameplay-Module bauen auf der freigegebenen Version auf.
- Jeder Pull Request nennt RE2-Build, REFramework-Version, getestete Rollen, Messwerte und bekannte Lücken. Ungetestete Engine-Funktionen bleiben ausdrücklich experimentell.
- Fremdmod-Dateien, Spiel-Assets, Steam-Binärdateien, persönliche Logs und Speicherstände dürfen nicht ins Repository.
- Bei Konflikten gilt: Host-Zustand und dokumentiertes Schema vor lokalen Beobachtungen; reproduzierbare Fehler werden als Issue mit Logauszug und Schritten erfasst.
