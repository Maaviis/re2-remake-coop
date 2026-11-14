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

`reframework/autorun/re2_coop_probe.lua` ist ein rein lesender REFramework-Einstiegspunkt. Er prüft im geladenen Spiel die Version der Typdatenbank sowie Spieler-, Transform- und Inventarobjekte und liest die Spielerposition und -rotation aus. Die Zugriffe folgen dem [REFramework-eigenen RE2-Hilfsskript](https://github.com/praydog/REFramework/blob/master/scripts/utility/RE2.lua) und den [Transform-Bindings](https://github.com/praydog/REFramework/blob/master/src/mods/bindings/Sdk.cpp). Die Anzeige nutzt die [ImGui-Schnittstelle](https://refdocs.praydog.com/api/imgui.html). Im Einzelinstanz-Test im Laborempfang hat die Probe sowohl die Objekttypen als auch eine Bewegung im geladenen Spiel erfasst.

Für die Bewegungsmessung das Skript in `reframework/autorun` der eigenen RE2-Installation kopieren und das Spiel mit einem passenden Spielstand starten. Im REFramework-Overlay unter **Script Generated UI** den Eintrag **RE2 Coop - integration probe** öffnen. Die Probe liest die Position ungefähr einmal pro 60 Update-Frames; **Movement observed** wechselt erst nach einer messbaren Positionsänderung auf `true`. Der einmalige Logeintrag `RE2_COOP_PROBE movement observed` ist der Nachweis für die lokale Messung, noch kein Nachweis für Koop-Synchronisation. Nach dem Test kann das Skript wieder aus `autorun` entfernt werden. Keine Speicherdateien für diese Probe kopieren oder verändern.

## Spielerpose zum v1-Gast übertragen

`reframework/autorun/re2_coop_observer.lua` liest alle sechs UpdateBehavior-Aufrufe Position und Rotation. Bei mindestens 0,01 Engine-Einheiten Abstand, 0,5 Grad Drehung oder zu Beginn der nächsten beobachteten Sekunde schreibt es `reframework/data/re2_coop_observer.json`. Fehlt eine gültige Pose, meldet es einmalig Abwesenheit, bis eine gültige Pose zurückkehrt. Der Observer nutzt die [REFramework-Callbacks](https://refdocs.praydog.com/api/re.html), [JSON-](https://refdocs.praydog.com/api/json.html) und [Dateifunktionen](https://refdocs.praydog.com/api/fs.html).

In TDB 70 liest der Observer zusätzlich Bank, ID, Namen und Frame-Werte des höchstgewichteten Animationsknotens von Schicht 0. Animationsänderungen erzeugen auch bei unveränderter Position eine neue Probe. `observer.py` prüft diese optionalen Werte und überträgt sie mit der Pose; `guest_pose.py` exportiert sie nach Prüfung in die Gastdatei. Fehlt eine gültige Animationsprobe, läuft die Positionsübertragung weiter. Der Gast stellt aus diesen Daten derzeit noch keine Animation dar: Die Zuordnung der lokalen Clipnamen zu einem passenden Gast-Asset und der Test mit zwei Instanzen bleiben offen.

Für einen Test mit einer RE2-Instanz Host, Gast und Observer in getrennten Terminals starten. Den Platzhalter im Dateipfad durch die Datei im RE2-Ordner ersetzen. Die ersten beiden Befehle starten Python-Prozesse für Host und Gast.

~~~sh
python wire.py host --port 45678 --protocol-version 1
python wire.py client --port 45678 --protocol-version 1 --listen --events 0
python observer.py --file "PFAD-ZU-RE2/reframework/data/re2_coop_observer.json" --port 45678 --player-id claire --protocol-version 1
~~~

Nach `READY` des Gasts `re2_coop_observer.lua` im REFramework ScriptRunner laden. Der Observer zeigt für bestätigte Proben `observer_sequence` und `host_sequence` an. Vor und nach einer Drehung auf der Stelle den aktuellen Snapshot in einem vierten Terminal mit `python wire.py client --port 45678 --protocol-version 1` abrufen. Erwartet wird eine neue Rotation bei stabiler Position. Für diesen Test genau einen Observer für `claire` starten. Bei einem neuen Lua-Lauf Host und Observer neu starten. Der Observer überspringt alte oder in die Zukunft datierte Proben.

`lua tests/test_observer_lua.lua` prüft mit Lua 5.4 die Bewegungserkennung und das Verhalten bei Schreibfehlern. Unter Linux kann das Programm `lua5.4` heißen. Der Python-Loopback-Test überträgt eine simulierte Probendatei bis zum Gastprozess. Die Anwendung der Pose in einer zweiten RE2-Instanz steht aus.

### Optionaler Gasttest für einen empfangenen Leon-Idle-Clip

`re2_coop_remote_motion.lua` liest die geprüfte Gastdatei und erzeugt nach einem Klick auf **Render verified remote Leon idle** oder einem frischen Terminalbefehl ein eigenes, sichtbares Testobjekt. Es akzeptiert derzeit ausschließlich Leons beobachteten Clip `pl00_0160_OFF_Gazing_Idle_F_Loop` (Schicht-Bank 1, Motion 160) und verwendet die in #23 lokal geprüfte `BareHand`-Variante als Darstellung. Das Objekt übernimmt die empfangene Position und Rotation; es verschwindet, wenn die Gastdatei älter als fünf Sekunden ist, die Sitzung wechselt, der Clip nicht mehr passt oder der lokale Kampagnenraum wechselt. Nach spätestens 20 Sekunden endet dieser Diagnoselauf ebenfalls.

Im Terminal kann `pwsh -File scripts/motion_probe.ps1 -Action Start -DataDirectory "PFAD-ZU-RE2/reframework/data"` die Diagnose aktivieren; mit `-Action Stop` wird das Testobjekt entfernt. Der Befehl wird atomar in den Datenordner geschrieben und nur innerhalb von fünf Sekunden mit neuer Kennung angenommen. Ein Start vor dem Laden der Kampagne wartet auf den Spieler und eine frische Gastpose. Die angenommene Anweisung und das Ergebnis stehen im REFramework-Log unter `RE2_COOP_MOTION_PLAYBACK`.

Der Gast setzt den lokalen Clip zunächst auf die relative Frame-Position der empfangenen Animation und korrigiert größere Abweichungen bei neuen Host-Sequenzen. Das ist eine experimentelle Annäherung: Der beobachtete `OFF`-Clip und die lokale `KFF`-Variante haben unterschiedliche Laufzeiten, und die Bildphase wurde noch nicht mit zwei Instanzen gemessen. Claire, andere Aktionen, Ausrüstung und Kopf/Haar-Mesh fehlen. Der Test ist standardmäßig deaktiviert; die neue Phasenangleichung benötigt noch einen nativen Nachweis.

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

### Transform-Schreibtest mit einem eigenen Spielobjekt

Der optionale Test nutzt die GameObject-Erzeugung aus dem
[REFramework Object Explorer](https://github.com/praydog/REFramework/blob/d1461375/src/mods/tools/ObjectExplorer.cpp)
und die dokumentierten [Transform-Setter](https://refdocs.praydog.com/api/types/RETransform.html).
Der Einzelinstanz-Test lief mit RE2 Steam-Build 11636119, REFramework-Commit
`d1461375` und TDB 70. In diesem Build sind
`create(System.String)` und `destroy(via.GameObject)` statische Methoden.

1. In einem geladenen Kampagnenraum den Diagnosemarker wie oben starten.
   Unter **Script Generated UI > RE2 Coop - remote pose** die Option
   **Apply pose to a test object (TDB 70)** aktivieren. Das Skript prüft
   die verfügbare Erzeugungs- und Aufräumschnittstelle vor der Objekterzeugung.
2. In der sendenden Instanz gehen und drehen. In der empfangenden Instanz
   sollten `RE2_COOP_GUEST_OBJECT verified`-Zeilen mit aufsteigenden
   Sequenzen, Position und Quaternion erscheinen. Das Skript liest den
   Transform des Testobjekts im nächsten `UpdateBehavior`-Aufruf zurück
   und vergleicht ihn mit der Vorgabe. So wird auch eine Abweichung nach
   dem dazwischenliegenden Engine-Update erkannt.
3. Bei weiter verbundenem Gast den Observer stoppen. Nach Ablauf der
   letzten Quellprobe müssen Marker und Testobjekt verschwinden. Vor
   **Reset scripts** oder einem Szenenwechsel die Schreiboption abschalten
   und **Test object: absent** im Overlay prüfen. Schlägt das Aufräumen fehl,
   zeigt das Overlay den Fehler und versucht es beim nächsten Update erneut.
4. Den Ablauf in zwei Instanzen im selben Kampagnenraum mit getrennten
   REFramework-Datenverzeichnissen wiederholen. Build, TDB, Sequenzen und
   Rücklesewerte festhalten. Bei Änderung des lokalen Spielerobjekts, des
   lokalen Szenenobjekts oder der Remote-Sitzung muss der Test erneut
   aktiviert werden.

Der Schreibtest bewegt das selbst erzeugte Objekt `RE2CoopRemotePoseTest`.
Es ist standardmäßig leer. Der Test mit simulierten Bindings prüft die
Aufrufreihenfolge. Im Einzelinstanz-Test im Laborempfang hat RE2 die
Position und Rotation der über Loopback übertragenen Spielerpose
zurückgemeldet. Nach Stopp der Weiterleitung blieb der Gast verbunden,
die Pose lief ab und das Overlay meldete `Test object: absent`.

### Render-Test mit der Schaufensterpuppe aus RE2

Vor dem Start des Schreibtests **Attach the stock mannequin** auswählen.
Das Skript lädt Mesh und Material der Schaufensterpuppe mit der
[REFramework-API für Ressourcen](https://refdocs.praydog.com/api/types/REResource.html)
und weist sie einer Render-Komponente auf demselben Testobjekt zu. Die
Ressourcen `sm32_256_mannequin01a_00ms.mesh.2109108288` und
`sm32_256_mannequin01a_00ms_mat.mdf2.21` wurden anhand der
[RE2-RT-Dateiliste](https://github.com/Ekey/REE.PAK.Tool/blob/19204e11bbd8365481a1dc97c9027dbf17ed6f7e/Projects/RE2_RT_STM_Release.list)
im lokalen PAK-Index von Build 11636119 gefunden. Das Skript bezieht sie
zur Laufzeit aus der Spielinstallation.

Im selben Kampagnenraum die sendende Figur aus der Distanz bewegen und drehen.
Auf der empfangenden Seite die Puppe und den Marker aus mehreren
Blickwinkeln vergleichen. Bei Stopp des Observers, Verbindungsverlust oder
nach Abschalten des Tests muss die Puppe verschwinden. Bei Fehlern die erste
`RE2_COOP_GUEST_OBJECT`-Meldung festhalten. Die Meldung
`mannequin resources assigned` bestätigt den Transform und die gemeldeten
Ressourcen nach dem Engine-Update. Für die Render-Abnahme ist die Puppe
in der 3D-Szene sichtbar und folgt Position und Drehung der gesendeten Pose.
Der Stellvertreter ist statisch. Animationen und Spieleraktionen sind noch offen.

Im Einzelinstanz-Test war die Puppe an zwei vom lokalen Spieler versetzten
Testpositionen sichtbar. Bei Sequenz 175 meldete die Engine die Position
`(-4.562, 0.028, -40.643)` mit Einheitsquaternion. Bei Sequenz 220 stand die
Puppe bei `(-4.770, 0.028, -40.890)` mit einer 90-Grad-Drehung um Y.
Die Testposen liefen über denselben v1-Host und Diagnosegast. Nach Stopp
des Gasts verschwanden Puppe und Marker. Der bidirektionale Lauf mit zwei
RE2-Instanzen steht aus.

### Posen in beide Richtungen übertragen

Beide Spieler verwenden denselben v1-Host und auf ihrem Rechner den gleichen
Repository-Stand. In beiden RE2-Installationen die eigenen Observer- und
Gastskripte laden und denselben Kampagnenraum öffnen. Die Testrollen
`leon` und `claire` bezeichnen die beiden Quellen im Protokoll.

Auf Rechner A den Host und in einem zweiten Terminal die Bridge starten.

~~~sh
python wire.py host --port 45678 --protocol-version 1
python pose_bridge.py --data "PFAD-ZU-RE2/reframework/data" --port 45678 --local-player-id leon --remote-player-id claire
~~~

Auf Rechner B kann ein bestehender SSH-Zugang zu A den Host-Port an das
lokale Loopback von B weiterleiten. Den Tunnel in einem eigenen Terminal
laufen lassen und die Bridge mit umgekehrten IDs starten.

~~~sh
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:45678:127.0.0.1:45678 BENUTZER@RECHNER-A
python pose_bridge.py --data "PFAD-ZU-RE2/reframework/data" --port 45678 --local-player-id claire --remote-player-id leon
~~~

Bei zwei getrennten Spielprozessen auf demselben Rechner entfällt der Tunnel.
Beide Bridges brauchen getrennte REFramework-Datenordner. Über zwei Rechner
die Systemuhren vorher abgleichen. Eine bis zu fünf Sekunden alte Probe
bleibt gültig. Proben aus der Zukunft werden verworfen.
[OpenSSH-Portweiterleitung](https://man.openbsd.org/ssh.1#L)

Die Bridge meldet `READY` nach einem geprüften Snapshot. Unter **RE2 Coop -
remote pose** auf beiden Seiten die Schaufensterpuppe und den Schreibtest
aktivieren. Zuerst A bewegen und auf B den Marker, die Puppe und das
Rücklesen der Pose beobachten. Anschließend die Rollen tauschen. Jede Seite
soll ausschließlich die jeweils andere Spieler-ID anzeigen. Wenn A ins
Hauptmenü zurückkehrt oder seine Bridge stoppt, soll seine Darstellung auf
B verschwinden. Bei einem Skript-Reset die betroffene Bridge neu starten.
Bei einem Host-Neustart beide Bridges neu starten. Pro Datenordner eine
Bridge betreiben. Die Bridge verwendet eine lokale Sperrdatei für weitere
Bridge-Aufrufe. Manuell gestartete Observer und Diagnosegäste für diesen
Ordner vorher beenden. Beim Beenden kann die Bridge noch auf einen
laufenden Netzwerkaufruf bis zu dessen Timeout warten.

`python -m unittest discover -s tests -p test_pose_bridge.py -v` prüft den
Transport in beide Richtungen mit separaten Datendateien und einem
gemeinsamen Loopback-Host. Der Test mit zwei laufenden RE2-Instanzen über
den SSH-Tunnel steht aus.

Die [REFramework-Nightly-Hinweise](https://github.com/praydog/REFramework-nightly/releases) unterscheiden den RT-Build von der alten Non-RT-Version. Die passende Variante muss vor Tests anhand des verwendeten Spiel-Builds ausgewählt werden.

## Prototyp ausführen

`python -m unittest discover -s tests -v`

## Nächste Entwicklungsstufen

1. Unterstützte RE2- und REFramework-Version festlegen; Engine-Typen und relevante Methoden im Spiel untersuchen.
2. Native REFramework-Bridge erstellen, die beobachtete Spielereignisse an den Host meldet und empfangene Zustände im Spiel anwendet. Zunächst zwei Spieler und Bewegung, dann Gegner und Interaktionen.
3. Steam-Lobby mit Einladung, Verbindungsstatus und Bereitschaft implementieren; Menüoberfläche an den Stil des Originals anlehnen.
4. Speicherstände und alle Skript-/Cutscene-Pfade kartieren; Host-Snapshots und Wiederverbindung im Spiel testen.
5. Zwei reale Spielinstanzen durch die gesamte Kampagne testen, mit Fehlerprotokoll für jede Ereigniskategorie und Versionskombination.
