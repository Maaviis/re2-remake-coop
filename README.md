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

Für die Bewegungsmessung die Probe in REFramework unter **ScriptRunner > Run script**
aus dem Checkout laden oder bei Installation in `reframework/autorun` das Spiel
starten. Einen Kampagnenspielstand laden und im Overlay unter **Script Generated UI**
den Eintrag **RE2 Coop - integration probe** öffnen.

Die Probe liest die Position alle 60 `UpdateBehavior`-Aufrufe. Bei einem
Spielerwechsel oder einer fehlenden bzw. ungültigen Positionsprobe verwirft sie
die Ausgangsposition. **Inspect loaded game** aktualisiert die Anzeige beim
nächsten `UpdateBehavior`-Aufruf. Der Knopf ändert den Messtakt nicht.

In einer stabilen Szene stehen bleiben, bis **Position samples** hochzählt und
**Movement observed** weiterhin `false` ist. Dann die Spielfigur bewegen und
prüfen, ob **Movement observed** auf `true` wechselt und einmal
`RE2_COOP_PROBE movement observed` im REFramework-Log erscheint. Für einen neuen
Versuch RE2 neu starten und die Probe erneut laden. Für [M0](https://github.com/Maaviis/re2-remake-coop/issues/1)
Spiel-Build, REFramework-Version, TDB und den Logeintrag festhalten.

Der Adressvergleich erkennt Objektwechsel an den Abtastpunkten. Ein Sprung
desselben Objekts kann ebenfalls eine Positionsänderung auslösen. Die Messung
einer Instanz liefert einen lokalen Nachweis der Positionsänderung.

Die [REFramework-Nightly-Hinweise](https://github.com/praydog/REFramework-nightly/releases) unterscheiden den RT-Build von der alten Non-RT-Version. Die passende Variante muss vor Tests anhand des verwendeten Spiel-Builds ausgewählt werden.

## Prototyp ausführen

Die Tests im Repository-Verzeichnis ausführen. Unter Windows heißt der
Lua-5.4-Befehl üblicherweise `lua`.

~~~sh
python -m unittest discover -s tests -v
lua5.4 tests/test_probe.lua
~~~

Der Lua-Test führt die Probe mit simulierten REFramework-Callbacks aus.

## Nächste Entwicklungsstufen

1. Unterstützte RE2- und REFramework-Version festlegen; Engine-Typen und relevante Methoden im Spiel untersuchen.
2. Native REFramework-Bridge erstellen, die beobachtete Spielereignisse an den Host meldet und empfangene Zustände im Spiel anwendet. Zunächst zwei Spieler und Bewegung, dann Gegner und Interaktionen.
3. Steam-Lobby mit Einladung, Verbindungsstatus und Bereitschaft implementieren; Menüoberfläche an den Stil des Originals anlehnen.
4. Speicherstände und alle Skript-/Cutscene-Pfade kartieren; Host-Snapshots und Wiederverbindung im Spiel testen.
5. Zwei reale Spielinstanzen durch die gesamte Kampagne testen, mit Fehlerprotokoll für jede Ereigniskategorie und Versionskombination.

