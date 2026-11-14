# RE2 Remake Koop – Entwicklungsstand

Dieses Verzeichnis enthält einen ausführbaren Prototyp des gemeinsamen Zustandsmodells. Es ist **noch keine im Spiel lauffähige Mod**.

Der [Anforderungsaudit](STATUS.md) trennt belegte Prototypfunktionen, Aussagen einer bereits installierten Fremdmod und offene Spieltests.

## Voraussetzungen und Befunde

- [REFramework](https://github.com/praydog/REFramework) unterstützt RE2 Remake und bietet Lua-Skripte sowie native Plugins.
- [Steam Matchmaking und Networking](https://partner.steamgames.com/doc/features/multiplayer/networking) bieten Lobby und Transport. Die praktische Einbindung in den RE2-Prozess und die Berechtigung zur Nutzung der Steamworks-Schnittstellen müssen noch geprüft werden.
- Die RE-Engine-Ereignisse für Gegner, Inventar, Skripte und Cutscenes sind noch nicht für eine konkrete Spielversion identifiziert. Ein Synchronisationskern allein kann diese Ereignisse nicht erfassen oder reproduzieren.
- Die Kompatibilität mit konkreten RE2-Builds und Mod-Managern muss für jede Testumgebung separat geprüft werden. Tests mit zwei Spielinstanzen sind offen.

## Architekturentscheidung

Der Host vergibt für jede Zustandsänderung eine fortlaufende Sequenznummer und eine eindeutige Sitzungskennung. Alle Clients wenden Ereignisse nur in dieser Reihenfolge und aus derselben Sitzung an. Wiederholte Ereignisse werden ignoriert. Ereignisse und Snapshots enthalten einen SHA-256-Prüfwert des Zustands; bei Abweichung wird die Änderung ohne Teilzustand verworfen. Nach einer Unterbrechung oder Prüfsummenabweichung fordert ein Client einen vollständigen Snapshot samt Sequenznummer an und verarbeitet erst danach neuere Ereignisse. Der Host führt den maßgeblichen Spielstand. Diese Prüfung erkennt Datenabweichungen, ersetzt aber keine Engine-Synchronisation oder Netzwerk-Authentifizierung.

`session.py` enthält den Lobby-Zustand für zwei Spieler, Spielstandauswahl, Einstellungen und Bereitschaft. Änderungen an der Konfiguration setzen die Bereitschaft zurück. Der gemeinsame Checkpoint wird vom Host atomar in eine Datei geschrieben und enthält die Zustandssequenz. Der Gast muss nach dem Laden oder Wiederverbinden zuerst diesen Snapshot übernehmen. Diese Datei ist ein **Prototypformat** und kein RE2-Speicherstand.

`wire.py` demonstriert über die lokale Loopback-Verbindung Host-Snapshot, laufende Ereignisverteilung an einen bereits verbundenen Gast und Wiederverbindung. Der Prozess-Test startet einen Host und zwei Client-Prozesse, vergleicht ihre Zustände nach einem Ereignis und prüft den Snapshot eines neu verbundenen Clients. Dieser Transport ist nur ein Entwicklungswerkzeug: Er verwendet weder Steam noch RE2 und akzeptiert noch unvalidierte Ereignisvorschläge. Er darf nicht als öffentlich erreichbarer Server eingesetzt werden.

Das Modell in `sync_model.py` hält Spielerpositionen und Aktionen, Gegnerleben und Tod, Schaden, Türen, Rätsel, Gegenstände, Inventar, Fortschritt, Skriptereignisse und Cutscene-Zustände. Es beweist **keine** Synchronisation im RE2-Prozess: Dafür müssen Ereignis-Hooks, IDs, Akteure, Animationen, Treffer, KI und Skriptübergänge pro Spielversion untersucht und angebunden werden.

`reframework/autorun/re2_coop_probe.lua` ist ein rein lesender REFramework-Einstiegspunkt. Er prüft im geladenen Spiel die Version der Typdatenbank sowie Spieler-, Transform- und Inventarobjekte und liest die Spielerposition und -rotation aus. Die Zugriffe folgen dem [REFramework-eigenen RE2-Hilfsskript](https://github.com/praydog/REFramework/blob/master/scripts/utility/RE2.lua) und den [Transform-Bindings](https://github.com/praydog/REFramework/blob/master/src/mods/bindings/Sdk.cpp); die Anzeige nutzt die [dokumentierte ImGui-Schnittstelle](https://refdocs.praydog.com/api/imgui.html). Ein erster Spielstart hat das Laden des Skripts und den Zugriff auf die relevanten Objekttypen bestätigt. Eine Bewegungsmessung im geladenen Spiel ist noch offen.

Für die Bewegungsmessung das Skript in `reframework/autorun` der eigenen RE2-Installation kopieren und das Spiel mit einem passenden Spielstand starten. Im REFramework-Overlay unter **Script Generated UI** den Eintrag **RE2 Coop - integration probe** öffnen. Die Probe liest die Position ungefähr einmal pro 60 Update-Frames; **Movement observed** wechselt erst nach einer messbaren Positionsänderung auf `true`. Der einmalige Logeintrag `RE2_COOP_PROBE movement observed` ist der Nachweis für die lokale Messung, noch kein Nachweis für Koop-Synchronisation. Nach dem Test kann das Skript wieder aus `autorun` entfernt werden. Keine Speicherdateien für diese Probe kopieren oder verändern.

Die [REFramework-Nightly-Hinweise](https://github.com/praydog/REFramework-nightly/releases) unterscheiden den RT-Build von der alten Non-RT-Version. Die passende Variante muss vor Tests anhand des verwendeten Spiel-Builds ausgewählt werden.

## Animationsdiagnose im Spiel

Kopiere `reframework/autorun/re2_coop_motion_probe.lua` nach `reframework/autorun` deiner RE2-Installation. Starte RE2 mit einer kompatiblen REFramework-Version, lade einen Kampagnenspielstand und bewege die Figur. Suche im lokalen `re2_framework_log.txt` nach `RE2_COOP_MOTION`. Die Probe ist auf RE2 mit TDB 70 begrenzt.

- `unavailable` meldet einen fehlenden Spieler, eine fehlende Motion-Schicht oder einen Lesefehler.
- `clip` zeigt die Motion-Bank, die Motion-ID und die Frame-Werte von `via.motion.TreeLayer` auf Schicht 0 an.
- `frame_changed` meldet die erste Frame-Änderung seit dem letzten `clip`-Eintrag. Dazu zählen auch Sprünge zurück, etwa an einer Schleifengrenze.

Bestätigt in einer Instanz von RE2 Build 11636119 mit REFramework `d1461375` in Leons Kampagne im Laborempfang. Dort wurden unterschiedliche Bank/ID-Paare sowie fortlaufende Frames gemessen. Die Werte stammen aus der Engine. Die Zuordnung zu Spielaktionen und die Wiedergabe auf einer Gastfigur müssen separat geprüft werden. Nach dem Test kann die Probe aus `autorun` entfernt werden.

Lokaler Lua-Test aus dem Repository-Stammverzeichnis:

```console
lua tests/test_motion_probe_lua.lua
```

## Prototyp ausführen

`python -m unittest discover -s re2-coop/tests -v`

## Nächste Entwicklungsstufen

1. Unterstützte RE2- und REFramework-Version festlegen; Engine-Typen und relevante Methoden im Spiel untersuchen.
2. Native REFramework-Bridge erstellen, die beobachtete Spielereignisse an den Host meldet und empfangene Zustände im Spiel anwendet. Zunächst zwei Spieler und Bewegung, dann Gegner und Interaktionen.
3. Steam-Lobby mit Einladung, Verbindungsstatus und Bereitschaft implementieren; Menüoberfläche an den Stil des Originals anlehnen.
4. Speicherstände und alle Skript-/Cutscene-Pfade kartieren; Host-Snapshots und Wiederverbindung im Spiel testen.
5. Zwei reale Spielinstanzen durch die gesamte Kampagne testen, mit Fehlerprotokoll für jede Ereigniskategorie und Versionskombination.

