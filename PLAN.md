# Arbeitsplan: RE2 Remake Koop

## Ziel und Stand

Ziel ist eine eigenständige Zwei-Spieler-Mod mit nachweislich gemeinsamem Spielzustand über die gesamte Kampagne. Auf dem Entwicklungszweig von PR #21 gibt es einen versionierten v1-Host, einen REFramework-Observer, einen Diagnosegast und eine Bridge für Posen in beide Richtungen. Ein Einzelinstanz-Test im Spiel bestätigte die Beobachtung und das Anwenden einer Pose an einem sichtbaren, statischen Testobjekt. Der bidirektionale Prozess-Test nutzte getrennte Datendateien; zwei echte Spielinstanzen wurden noch nicht gemeinsam geprüft. Eine spielbare Mod existiert noch nicht. [STATUS.md](STATUS.md) führt alle offenen Anforderungen und Nachweise auf.

Eine veröffentlichte Fremdmod dient nur als Vergleich; ihre Dateien oder Assets werden wegen der veröffentlichten Änderungsrechte nicht übernommen.

## Aktualisierte Aufgabenfolge (14. November 2026)

Die Entwürfe #8 bis #31 sind offen. #22 beobachtet Animationsbank, Clip und Frames des Kampagnenspielers; #23 spielt einen installierten Leon-Idle-Clip auf einem eigenen sichtbaren Testobjekt ab. #24 sichert die Host-Autorität im lokalen Lobby-Modell. #25 trägt Animationsdaten durch die v1-Posenkette; das native Lesen und die Übertragung einer Claire-Probe bis zur Gastdatei wurden in einer Spielinstanz bestätigt. #26 rendert optional einen empfangenen Leon-Idle-Clip auf einem eigenen Testobjekt; ein nativer Einzelinstanz-Test mit synthetischer Gastpose bestätigte diesen Clip, echte Leon-Sendedaten und zwei Instanzen stehen aus. #27 verwirft veraltete Bereitschaft nach Wiederbeitritt. #28 bis #30 prüfen private Steam-Lobbys, Einladungseingang und einen Nachrichtenkanal im laufenden RE2; ein echter Roundtrip zwischen zwei Konten steht aus. #31 erprobt eine relative Clip-Phasenangleichung als Entwurf, bisher nur mit Lua-Tests und bestätigter Engine-Methode. Diese Probes ersetzen keinen Zwei-Spieler-Nachweis. #21 baut auf #20 sowie früheren Entwürfen auf. Sein zuvor gemeldeter Dokumentationskonflikt ist behoben; GitHub meldet den Entwurf wieder als zusammenführbar. Ein neuer Host-Test prüft, dass ein nicht lesender Peer den Ereignisversand an andere Peers nicht blockiert. Die Basis `main` enthält die neueren Funktionen noch nicht. Vor weiteren Gameplay-Arbeiten wird die PR-Kette in Abhängigkeitsfolge geprüft, die Tests je Integrationsschritt ausgeführt und die Zweig-Abhängigkeiten aufgelöst. Keine der offenen Arbeiten gilt allein durch einen bestandenen CI-Lauf als im Spiel abgenommen.

1. **Integration und Architektur (#1):** v1-Protokoll, Digest-Prüfung, Dauerevents und Handshake aus #8, #10, #12 und #13 in kleinen, nachvollziehbaren Schritten integrieren; danach die Observer- und Gastkette #9, #11, #14 bis #21 prüfen. Für jeden Schritt Schnittstelle, Tests und Abhängigkeit festhalten.
2. **RE2-Spieler und Kampf (#2):** #21 mit zwei echten RE2-Instanzen im selben Raum testen: getrennte Datenordner, beide Bewegungsrichtungen, Rotation, Sichtbarkeit, Abwesenheit und Wiederbeitritt. Die in #25 angelegte Kette mit zwei echten Spielinstanzen prüfen. Für #26 echte Leon-Sendedaten und die Darstellung im zweiten Spielprozess testen. Die Phasenabbildung aus #31 nativ messen und nur bei passender Clip-Zuordnung übernehmen; danach die kontrollierte Zuordnung von Spieleraktion zu Clip, Übertragung über die v1-Sitzung und Wiedergabe auf dem Gastobjekt erweitern. Diese Integration braucht danach den Zwei-Instanzen-Nachweis; anschließend Gegner-IDs, Treffer, Schaden und Tod.
3. **Qualitätssicherung (#7):** Einzelinstanz-Nachweis, Prozesssimulation und Zwei-Instanzen-Nachweis getrennt protokollieren. Build, TDB, Sequenzen und beobachtete Abweichungen erfassen; keine lokalen Pfade, Kontodaten oder Speicherdateien veröffentlichen.
4. **Steam-Lobby (#5) und Speichern (#6):** das Host- und Revisionsmodell aus #24/#27 mit den Steam-Probes #28–#30 verbinden. Zuerst Einladung und `ping` mit zwei Konten prüfen; danach den v1-Spielzustand über den Transport führen, Menü und echte Spielstandanbindung anschließen. Für lokale Spieltests nur ausdrücklich freigegebene Speicherstände verwenden.
5. **Welt (#3) und Kampagne (#4):** stabile Objekt-IDs, Inventar und Rätsel sowie Skripte und jede Zwischensequenz mit eigenen Zwei-Instanzen-Tests anbinden. Diese Pakete bleiben offen.

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
