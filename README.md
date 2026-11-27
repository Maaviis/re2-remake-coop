# Resident Evil 2 Remake Coop

Steam-Koop für die Kampagne von **Resident Evil 2 Remake**. Zwei Spieler starten RE2 über Steam, treffen sich in einer privaten Lobby und starten gemeinsam dieselbe Geschichte. In Leons Geschichte soll der Host Leon und der Gast Claire steuern. In Claires Geschichte sind die Rollen umgekehrt.

**Status · Koop-Prototyp in Entwicklung**

Einzeltests in RE2 erreichen die Kampagne. Die durchgehende Abnahme mit zwei echten RE2-Instanzen und zwei Steam-Konten steht aus.

[Projekt-Score](#projekt-score) · [Aktueller Stand](#aktueller-stand) · [Testbuild starten](#testbuild-starten) · [Mitwirken](#mitwirken)

## Projekt-Score

### 57 / 100

```text
██████████████░░░░░░░░░░░  57 %
```

**Eigene technische Einschätzung · 26. November 2026**

Der Score schätzt den Entwicklungsfortschritt auf dem Weg zu einer vollständigen Koop-Kampagne. Er bewertet Code, reproduzierbare Tests und Beobachtungen im Spiel. Die Endabnahme fließt separat ein. Die Gesamtwertung ist der gerundete gewichtete Mittelwert der Teilwerte.

| Bereich | Gewicht | Score | Woran ich das festmache |
| --- | ---: | ---: | --- |
| Steam-Lobby und Verbindung | 20 % | **80 / 100** | Steam-Direktstart, private Lobbys, Einladungen und Bereitschaft sind umgesetzt. Fokuswechsel und Wiederbeitritt brauchen die Abnahme eines durchgehenden Ablaufs. |
| Kampagnenstart und Speichern | 20 % | **65 / 100** | Der geschützte Start ohne alten Szenario-Spielstand hat einen Einzelpfad in RE2. Gemeinsame Freigabe sowie Speichern, Fortsetzen und Wiederbeitritt sind die offenen Integrationspunkte. |
| Spielfiguren und Animationen | 25 % | **35 / 100** | Position, Ausrichtung und Animationsdaten haben einen Transportpfad. Claire wurde im Solotest als Vorschau mit laufendem Standclip beobachtet. Unabhängige Gaststeuerung und sichtbare Laufanimationen in beiden Richtungen stehen aus. |
| Zwischensequenzen | 10 % | **70 / 100** | Start nach Ankunft beider Spieler und gemeinsames Überspringen sind implementiert. Drei frühe Szenen wurden in RE2 mit simuliertem Gast beobachtet. Weitere Szenen und die Zwei-PC-Prüfung fehlen. |
| Welt, Kampf und Inventar | 15 % | **30 / 100** | Es gibt Code und gezielte Prüfungen für Gegner-HP, Treffer und Zustandsbeobachtung. Ein konsistenter gemeinsamer Weltzustand über eine Kampagne hinweg steht aus. |
| Windows-Build und Diagnostik | 10 % | **80 / 100** | CI baut beide nativen Plugins und das Steam-ZIP. Der Build enthält die Bridge und ihre Python-Laufzeit. Der Testablauf nutzt isolierte Profile und protokolliert fehlende Spielstands- oder Freigabebelege. |

**Mein Urteil:** Der Unterbau hat die frühe Forschungsphase hinter sich. Der größte Sprung zur Spielbarkeit sind zwei unabhängig steuerbare und gegenseitig sichtbare Figuren mit verlässlicher Weltfreigabe. Erst ein stabiler gemeinsamer Einstieg macht aussagekräftige Tests für Kampf, Checkpoints und längere Spielabschnitte möglich.

## Aktueller Stand

| Evidenz | Belegt |
| --- | --- |
| **E2 · Automatisierte Tests** | Windows-ZIP sowie Python-, Lua- und native Tests. Zwei simulierte Endpunkte tauschten die verpackten Szenennachrichten aus und prüften Ankunft, Ablehnung, Zustimmung und kurze Übertragungsunterbrechungen. |
| **E3 · Ein echtes RE2** | Ein geschützter Solostart erreichte den spielbaren Abschnitt. Trucker-Intro, Leon im Auto und Tankstelleneingang wurden mit simuliertem Gast bis zum nativen Szenenende beobachtet. Eine separate F5-Vorschau bestätigte Claires Modell mit einem Standclip. |
| **E4 · Zwei echte RE2-Instanzen** | Offen. Beide Spieler müssen gemeinsam starten, sich bewegen, einander sehen und Verbindung, Szenenwechsel sowie Wiederbeitritt im selben Testlauf prüfen. |

Die E3-Nachweise stammen aus den Testbuilds des [Zwischensequenzen-PRs](https://github.com/Maaviis/re2-remake-coop/pull/156). Die [Zwei-PC-Endabnahme](https://github.com/Maaviis/re2-remake-coop/issues/158) enthält den Ablauf für Lobby, Kampagnenstart und die ersten Zwischensequenzen. [Spielerfigur und Laufanimation](https://github.com/Maaviis/re2-remake-coop/issues/2) sowie [Checkpoints und Fortsetzen](https://github.com/Maaviis/re2-remake-coop/pull/157) sind laufende Entwicklungsarbeiten. Details zur Freigabe und Dateisicherung stehen in [SHARED_LOAD.md](docs/campaign/SHARED_LOAD.md) und [SAVE_PROTECTION.md](docs/campaign/SAVE_PROTECTION.md).

## Testbuild starten

1. Öffnet einen erfolgreichen [Windows-Build von `main`](https://github.com/Maaviis/re2-remake-coop/actions/workflows/protocol-tests.yml?query=branch%3Amain). Ladet das Artefakt `re2-koop-steam-…` und verwendet auf beiden PCs dasselbe enthaltene ZIP. Vergleicht die SHA-256 mit der beiliegenden Prüfsumme.
2. Verwendet Windows x64, die Steam-Version von RE2 mit dem getesteten Build **11636119** und ein installiertes [REFramework](https://github.com/praydog/REFramework) für **TDB 70**. Sichert vorhandene Moddateien bei geschlossenem Spiel. Kopiert `reframework` und `re2-coop` aus dem ZIP neben `re2.exe`.
3. Verwendet pro PC ein isoliertes Testprofil mit echten, von RE2 angelegten Systemdaten. Sichert die privaten Spielstände vor dem Test und deaktiviert Steam Cloud für RE2 auf beiden PCs. Für **Neues Spiel** braucht ihr keinen alten Szenario-Spielstand.
4. Klickt in Steam auf **Spielen** und öffnet **Multiplayer**. Der Host erstellt eine private Lobby und lädt den Gast ein. Der Host klickt auf **Neues Spiel** und wählt Szenario und Schwierigkeit. Der Gast bleibt im Titelmenü, während sein Spiel den lokalen Koop-Ordner automatisch vorbereitet. Sobald beide bereit sind, klickt der Host auf **Spiel starten**.

**Allein testen:** Die private Host-Lobby leer lassen und nach der Vorbereitung **Solotest starten (Leon A, Normal)** wählen. F2 meldet die Ankunft des simulierten Gasts. Im freien Spiel schaltet F5 die Figurenvorschau ein. Die vollständige Tastenbelegung steht in `ZUERST_LESEN.txt` im ZIP.

Die [technische Dokumentation](docs/README.md) bündelt Anleitungen zu Lobby, Kampagne, Speicherständen und Engine-Beobachtern.

## Wie der Mod aufgebaut ist

Bei einer verbundenen Steam-Lobby sammelt der Host die Koop-Diagnosen beider PCs automatisch unter
`reframework/data/re2_coop_logs/<Sitzungs-ID>/timeline.jsonl` im RE2-Ordner. Öffnet für den letzten
Versuch die zuletzt geänderte Zeitleiste. Jede Zeile enthält Host oder Gast, die Uhrzeit des
Ereignisses und die Empfangszeit beim Host (beide UTC). So lassen sich auch bei unterschiedlichen
PC-Uhren Lobbyfehler, Szenenentscheidungen und der Verlust der Kampagnenfreigabe vergleichen.
Übertragen werden ausgewählte Modmeldungen und technische Fehlerdaten. Private Dateipfade,
Steam-Konten und Spielstände bleiben lokal. Bereits empfangene Ereignisse bleiben nach einem
Abbruch lesbar. Ein Gast, der vor dem Verbindungsaufbau ausfällt, kann keine Meldung übertragen.

Für Cutscene-Fehler speichert der Host im selben Sitzungsordner auch die zeitliche Folge seiner eigenen Szene und der empfangenen Gastzustände. Diese Aufnahme lässt sich im geschützten Solotest mit einem simulierten Gast abspielen. [Aufnehmen und wiedergeben](docs/testing/SESSION_REPLAY.md)

| Baustein | Aufgabe |
| --- | --- |
| [REFramework und Lua](reframework/) | Lobby im Titelmenü, native Kampagnen- und Szenenanbindung, Beobachtung des lokalen Spielers, Darstellung des Partners. |
| [Windows-Plugins](network/) | Steam-Lobby, Verbindung, lokale Kommunikation und nativer Speicherschutz. |
| [Steam-Bridge](bridge/steam_pose_bridge.py) und [Protokoll](bridge/protocol/) | Übertragen und prüfen Lobby, Posen, Kampagnenfreigabe, Kampfbelege und Szenenentscheidungen. |
| [Tests](tests/) und [Paketbau](tools/test_package/) | Regressionstests und ein Windows-Testpaket mit festgehaltenem Quellcommit. |

## Mitwirken

`main` ist der gemeinsame Integrationsstand. Fertige Änderungen gehen nach technischer Prüfung auf `main`. Offene Spielabnahmen stehen anschließend als Issues mit Build, Testschritten und erwarteten Ergebnissen bereit.

Bei einem Fehler bitte Build, Host- oder Gastrolle, letzte erfolgreiche Aktion und den relevanten Logauszug angeben. Für Grafik- oder Animationsfehler hilft ein kurzer Clip von beiden Seiten. Spielstände und Zugangsdaten gehören nicht ins Issue. [Issues öffnen](https://github.com/Maaviis/re2-remake-coop/issues)

Python-Tests aus dem Repository-Verzeichnis starten:

```sh
python tools/run_tests.py
```

Der [CI-Workflow](.github/workflows/protocol-tests.yml) führt zusätzlich Lua- und Windows-Tests aus. Weitere technische Einstiege sind [Steam-Posentest](docs/lobby/STEAM_POSE_TEST.md), [Protokoll](bridge/protocol/README.md) und [Entwicklungsplan](docs/project/PLAN.md).

## Lizenz

Der Mod-Code steht unter der [MIT-Lizenz](LICENSE). Ihr benötigt eine eigene Kopie von Resident Evil 2 Remake. Modelle und Animationen werden aus der lokalen Spielinstallation geladen.
