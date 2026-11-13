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

`wire.py` demonstriert über die lokale Loopback-Verbindung Host-Snapshot, laufende Ereignisverteilung an einen bereits verbundenen Gast und Wiederverbindung. Der Prozess-Test startet einen Host und zwei Client-Prozesse, vergleicht ihre Zustände nach zwei Ereignissen und prüft den Snapshot eines neu verbundenen Clients. Dieser Transport ist nur ein Entwicklungswerkzeug: Er verwendet weder Steam noch RE2 und akzeptiert noch unvalidierte Ereignisvorschläge. Er darf nicht als öffentlich erreichbarer Server eingesetzt werden.

Ein Gast kann mit `python wire.py client --port 45678 --listen --events 0` dauerhaft auf Host-Ereignisse warten. Der Prozess-Test prüft zwei aufeinanderfolgende Ereignisse in derselben Gastverbindung und einen danach neu verbundenen Gast. Der allgemeine CLI-Client beendet sich bei Verbindungsende. Der v1-Diagnosegast `guest_pose.py` kann sich automatisch wiederverbinden.

Das Modell in `sync_model.py` hält Spielerpositionen und Aktionen, Gegnerleben und Tod, Schaden, Türen, Rätsel, Gegenstände, Inventar, Fortschritt, Skriptereignisse und Cutscene-Zustände. Es beweist **keine** Synchronisation im RE2-Prozess: Dafür müssen Ereignis-Hooks, IDs, Akteure, Animationen, Treffer, KI und Skriptübergänge pro Spielversion untersucht und angebunden werden.

`reframework/autorun/re2_coop_probe.lua` ist ein rein lesender REFramework-Einstiegspunkt. Er prüft im geladenen Spiel die Version der Typdatenbank sowie Spieler-, Transform- und Inventarobjekte und liest die Spielerposition und -rotation aus. Die Zugriffe folgen dem [REFramework-eigenen RE2-Hilfsskript](https://github.com/praydog/REFramework/blob/master/scripts/utility/RE2.lua) und den [Transform-Bindings](https://github.com/praydog/REFramework/blob/master/src/mods/bindings/Sdk.cpp); die Anzeige nutzt die [dokumentierte ImGui-Schnittstelle](https://refdocs.praydog.com/api/imgui.html). Ein erster Spielstart hat das Laden des Skripts und den Zugriff auf die relevanten Objekttypen bestätigt. Eine Bewegungsmessung im geladenen Spiel ist noch offen.

Für die Bewegungsmessung das Skript in `reframework/autorun` der eigenen RE2-Installation kopieren und das Spiel mit einem passenden Spielstand starten. Im REFramework-Overlay unter **Script Generated UI** den Eintrag **RE2 Coop - integration probe** öffnen. Die Probe liest die Position ungefähr einmal pro 60 Update-Frames; **Movement observed** wechselt erst nach einer messbaren Positionsänderung auf `true`. Der einmalige Logeintrag `RE2_COOP_PROBE movement observed` ist der Nachweis für die lokale Messung, noch kein Nachweis für Koop-Synchronisation. Nach dem Test kann das Skript wieder aus `autorun` entfernt werden. Keine Speicherdateien für diese Probe kopieren oder verändern.

## Spielerpose zum v1-Gast übertragen

`reframework/autorun/re2_coop_observer.lua` liest alle sechs UpdateBehavior-Aufrufe Position und Rotation. Bei mindestens 0,01 Engine-Einheiten Abstand, 0,5 Grad Drehung oder zu Beginn der nächsten beobachteten Sekunde schreibt es `reframework/data/re2_coop_observer.json`. Fehlt eine gültige Pose, meldet es einmalig Abwesenheit, bis eine gültige Pose zurückkehrt. Der Observer nutzt die [REFramework-Callbacks](https://refdocs.praydog.com/api/re.html), [JSON-](https://refdocs.praydog.com/api/json.html) und [Dateifunktionen](https://refdocs.praydog.com/api/fs.html).

Für einen Test mit einer RE2-Instanz Host, Gast und Observer in getrennten Terminals starten. Den Platzhalter im Dateipfad durch die Datei im RE2-Ordner ersetzen. Die ersten beiden Befehle starten Python-Prozesse für Host und Gast.

~~~sh
python wire.py host --port 45678 --protocol-version 1
python wire.py client --port 45678 --protocol-version 1 --listen --events 0
python observer.py --file "PFAD-ZU-RE2/reframework/data/re2_coop_observer.json" --port 45678 --player-id claire --protocol-version 1
~~~

Nach `READY` des Gasts `re2_coop_observer.lua` im REFramework ScriptRunner laden. Der Observer zeigt für bestätigte Proben `observer_sequence` und `host_sequence` an. Vor und nach einer Drehung auf der Stelle den aktuellen Snapshot in einem vierten Terminal mit `python wire.py client --port 45678 --protocol-version 1` abrufen. Erwartet wird eine neue Rotation bei stabiler Position. Für diesen Test genau einen Observer für `claire` starten. Bei einem neuen Lua-Lauf Host und Observer neu starten. Der Observer überspringt alte oder in die Zukunft datierte Proben.

`lua tests/test_observer_lua.lua` prüft mit Lua 5.4 die Bewegungserkennung und das Verhalten bei Schreibfehlern. Unter Linux kann das Programm `lua5.4` heißen. Der Python-Loopback-Test überträgt eine simulierte Probendatei bis zum Gastprozess. Die Anwendung der Pose in einer zweiten RE2-Instanz steht aus.

## Empfangene Pose in REFramework anzeigen

Für den Diagnosetest `re2_coop_guest_pose.lua` im ScriptRunner der empfangenden
Instanz laden. Der Python-Gast übernimmt den geprüften v1-Snapshot und schreibt
die Pose der gewählten Spieler-ID nach `reframework/data/re2_coop_guest_pose.json`
der empfangenden Instanz.

~~~sh
python guest_pose.py --port 45678 --remote-player-id claire --output "PFAD-ZU-RE2/reframework/data/re2_coop_guest_pose.json"
~~~

- **Ein Spielprozess:** Zum Prüfen des Markers bei laufendem Host eine Position
  über den Observer übertragen. Den Marker in derselben Instanz laden und die
  Kamera auf die übertragene Position richten.
- **Zwei Spielprozesse:** Beide Instanzen im selben Kampagnenraum und mit
  getrennten REFramework-Datenverzeichnissen starten. Den Observer in der
  sendenden Instanz laden und im Sichtfeld der empfangenden Instanz gehen und
  auf der Stelle drehen. Der Marker soll die Position und die aus dem
  Quaternion berechnete lokale +Z-Achse anzeigen. Der aktuelle Transport
  ist auf Loopback begrenzt.
- Den Python-Gast mit Strg+C beenden. Der Marker soll verschwinden. Bei
  abruptem Prozessende wird der Marker ausgeblendet, sobald der Dateistempel
  älter als fünf Sekunden ist. Ein laufender Gast erneuert den Dateistempel
  auch bei stillstehender Spielfigur. Für jeden Ausgabepfad genau einen Gast
  starten.
- Bei laufendem Host und Gast in der sendenden Instanz zum Hauptmenü zurückkehren.
  Der Marker soll nach der Abwesenheitsmeldung verschwinden. Endet der
  Observer ohne Meldung, wird die letzte zeitgestempelte Pose nach fünf
  Sekunden ungültig. Standproben halten den Marker sichtbar, solange der
  Observer gültige Daten liefert. Beide Prozesse verwenden auf Loopback
  dieselbe Systemzeit. Ältere Pose-Formate ohne Quellzeitstempel behalten
  die bisherige Sichtbarkeit bei bestehender Verbindung.

Bei erkanntem Verbindungsverlust blendet der Diagnosegast die Pose aus.
`--reconnect-attempts 3` erlaubt drei weitere Verbindungsversuche über die
Laufzeit des Gasts. `0` schaltet automatische Wiederverbindung ab. Der Gast
zeigt erst nach erfolgreichem v1-Handshake und geprüftem Snapshot derselben
Sitzung wieder eine Pose. Bei einem Neustart des Hosts mit neuer
Sitzungskennung den Gast gezielt neu starten. TCP-Keepalive unterstützt die
Erkennung eines nicht mehr erreichbaren TCP-Peers. Mit `--host-heartbeat`
prüft der Diagnosegast auch die Antwort des Host-Prozesses. Fehlt die Antwort
auf eine Anfrage fünf Sekunden lang, blendet er die Pose aus und verbindet
sich erneut. Diese Option setzt einen v1-Host mit Unterstützung für `ping`
und `pong` voraus. Details stehen in der [Protokollbeschreibung](protocol/README.md).

`lua tests/test_guest_pose_lua.lua` prüft die Markerausgabe mit simulierten
REFramework-Callbacks. Der Marker ist eine Diagnoseanzeige. Eine zweite
Spielfigur und die Szenenzuordnung bleiben offen.

Die [REFramework-Nightly-Hinweise](https://github.com/praydog/REFramework-nightly/releases) unterscheiden den RT-Build von der alten Non-RT-Version. Die passende Variante muss vor Tests anhand des verwendeten Spiel-Builds ausgewählt werden.

## Prototyp ausführen

`python -m unittest discover -s tests -v`

## Nächste Entwicklungsstufen

1. Unterstützte RE2- und REFramework-Version festlegen; Engine-Typen und relevante Methoden im Spiel untersuchen.
2. Native REFramework-Bridge erstellen, die beobachtete Spielereignisse an den Host meldet und empfangene Zustände im Spiel anwendet. Zunächst zwei Spieler und Bewegung, dann Gegner und Interaktionen.
3. Steam-Lobby mit Einladung, Verbindungsstatus und Bereitschaft implementieren; Menüoberfläche an den Stil des Originals anlehnen.
4. Speicherstände und alle Skript-/Cutscene-Pfade kartieren; Host-Snapshots und Wiederverbindung im Spiel testen.
5. Zwei reale Spielinstanzen durch die gesamte Kampagne testen, mit Fehlerprotokoll für jede Ereigniskategorie und Versionskombination.
