# v1-Posenbridge über Steam prüfen

Der optionale Austausch von Lobby-Auswahl und Bereitschaft ist in
[LOBBY_TEST.md](LOBBY_TEST.md) beschrieben.

Dieser Entwurf verbindet die beiden bestätigten Teilnehmer einer privaten
RE2-Koop-Lobby mit der vorhandenen v1-Posenbridge. Steam transportiert JSON-
Nachrichten mit maximal 4096 Byte auf einem eigenen zuverlässigen Kanal.
Eine lokale Windows-Pipe verbindet das REFramework-Plugin mit Python.
Der Host behält die Autorität über Sitzung, Sequenz und Zustandsdigest.
Der Gast kann ausschließlich seine konfigurierte Spielerpose vorschlagen.

## Test auf zwei Rechnern

1. Auf beiden Rechnern dasselbe Commit und denselben unterstützten RE2-Build
   verwenden. Jede Bridge prüft ihre lokale Observer-Probe gegen die eigene
   Uhr. Der Steam-Pfad beginnt die fünfsekündige Anzeigefrist beim Empfang
   auf dem jeweiligen Rechner; die Systemuhren müssen dafür nicht abgeglichen
   werden. Der Host entfernt abgelaufene Posen mit einem sequenzierten
   v1-Event aus seinem verbindlichen Zustand. Ein späterer Snapshot enthält
   dann keinen alten Transform oder Clip. Pro Spieler sperrt der Host bis zu
   256 abgelöste Observer-Läufe gegen verspätete Nachrichten; am Limit sind
   weitere Laufwechsel erst in einer neuen Host-Sitzung möglich.
2. Das Plugin nach [der Bauanleitung](network/steam_lobby_probe/README.md)
   installieren. In beide REFramework-`autorun`-Ordner
   `re2_coop_observer.lua` und `re2_coop_guest_pose.lua` kopieren.
   Für den optionalen Animationsvergleich zusätzlich
   `re2_coop_remote_motion.lua` in den Gast-`autorun`-Ordner kopieren.
   Die beiden Rechner verwenden eigene REFramework-Datenordner.
3. Der Host erstellt die Steam-Lobby und lädt das vereinbarte Gastkonto ein.
   Der Gast nimmt die Einladung an und führt `join-invite` aus.
   Mit `peer-status` und `ping` vorher in beiden Richtungen prüfen,
   ob der jeweilige Peer tatsächlich antwortet.
4. Im Repository-Verzeichnis die jeweilige Bridge starten. Rollen und beide
   Spieler-IDs müssen auf beiden Rechnern übereinstimmen. Pro Datenordner
   läuft eine Bridge. `--pid` erhält die PID des jeweiligen RE2-Prozesses.

~~~powershell
$re2Pid = (Get-Process -Name re2).Id
python steam_pose_bridge.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data"
# Auf dem Gastrechner:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data"
~~~

5. In beiden Instanzen denselben Kampagnenraum laden. Die Diagnoseanzeige
   `RE2 Coop - remote pose` zeigt jeweils die Gegenstelle. Position und
   Drehung nacheinander in beiden Richtungen prüfen. Bei Host Leon und Gast
   Claire den beobachteten Leon-Idle-Clip abwarten. Auf dem Gast kann dann
   `pwsh -File scripts/motion_probe.ps1 -Action Start -DataDirectory
   "PFAD-ZU-RE2/reframework/data"` die optionale animierte Darstellung
   einschalten. Im REFramework-Log `RE2_COOP_MOTION_PLAYBACK` auf Clipname,
   Phasen-Readback und spätere Entfernung prüfen. Die relative Phase ist
   experimentell und noch nicht mit zwei echten Spielinstanzen gemessen.
6. Die Python-Host-Bridge beenden, während die Steam-Lobby bestehen bleibt.
   Die Gastpose muss nach dem Timeout verschwinden. Die Host-Bridge neu
   starten und prüfen, dass die laufende Gast-Bridge nach einem neuen
   `hello` automatisch die neue Host-Sitzung übernimmt. Sitzungskennung und
   Pose auf beiden Seiten vergleichen. Der Gast darf nur den Snapshot mit
   der Kennung seiner aktuellen Anfrage und gültigem Digest übernehmen.
   Der neue Host verwirft Posen-Vorschläge mit der alten Sitzungskennung.
   Danach die Gast-Lobby verlassen;
   auf der Gegenseite muss die Pose wieder verschwinden.

## Terminal-Check pro Rechner

Für einen Menütest vor der Einladung die Bridge mit `--lobby` und der
passenden Rolle starten. Beide Seiten können dann im Titelmenü prüfen,
ob Dateistand, laufende Instanz, Rollenzuordnung und Steam-Lobbystatus
zusammenpassen. Dazu kommt der frische Status der geladenen Menü-Eingabe.

~~~powershell
python steam_pose_preflight.py --stage menu --game "PFAD-ZU-RE2" --dll "PFAD-ZUM-TESTBUILD/re2_coop_steam_lobby_probe.dll" --pid $re2Pid --role host
~~~

Im Menümodus benötigt der Check weder Partner noch Spielfigur. Der Status
`different-process` weist auf die falsche RE2-PID oder eine ältere Bridge
ohne PID im Lobbybericht hin. `wrong-role` weist auf eine vertauschte
Host-/Gast-Konfiguration hin. Bei `lobby-state-mismatch` nach dem
Statuswechsel erneut prüfen. Die Bedienung per Taste oder Mausklick
bleibt ein eigener Schritt im Spiel.

In RE2 Steam-Build 11636119 mit REFramework d1461375 bestand der Menücheck
in einer isolierten Instanz nacheinander für die Host-Bridge im Zustand
`idle` und mit privater Solo-Lobby (`owned`) sowie für die Gast-Bridge in
`idle`. Eine vertauschte Rolle lieferte `wrong-role`. Die Solo-Lobby wurde
per Terminal erstellt und verlassen. Einladung und Datenaustausch über
zwei Steam-Konten bleiben offen.

Nach dem Lobbybeitritt, einem erfolgreichen `ping` auf dieser Seite und dem
Laden des Kampagnenraums den lokalen Stand prüfen. Der Check benötigt Windows,
Python 3.11 oder neuer, PowerShell 7 (`pwsh` im PATH) und die DLL aus dem
eigenen Testbuild. Auf dem Gast `--role guest` verwenden. `--motion` prüft
zusätzlich das optionale Motion-Skript, wenn es auf diesem Rechner für den
Test installiert sein soll.

~~~powershell
python steam_pose_preflight.py --game "PFAD-ZU-RE2" --dll "PFAD-ZUM-TESTBUILD/re2_coop_steam_lobby_probe.dll" --pid $re2Pid --role host
~~~

Der JSON-Bericht nennt die Rolle, den Status der einzelnen Prüfungen und
`ready`. Exitcode 0 bedeutet, dass die Dateihashes passen, der Prozess zur
Installation gehört, die Lobby-Rolle und der Steam-Roundtrip bestätigt sind
und der Observer eine frische TDB-70-Spielerpose meldet. Bei Exitcode 1 zeigen
`checks` die offenen Voraussetzungen. `peer-waiting-for-member` steht für
eine Lobby ohne bestätigten Peer. `player-unavailable` kann im Hauptmenü
auftreten.

Der Check sendet nur Statusbefehle an die Lobby-Pipe. Der Dateivergleich
bezieht sich auf die Dateien auf der Festplatte. Den Posenaustausch und das
Verhalten des Gastobjekts prüfen die anschließenden Schritte im Spiel.
`ready` bestätigt nur diese Voraussetzungen. Es bestätigt weder eine
gemeinsame Kampagne noch Gegner-, Welt- oder Cutscene-Synchronisation.
Der kombinierte Prüfstand mit Ladeadapter und passiver Ablaufspur ist
in [INTEGRATION_LOAD_TOOLS.md](INTEGRATION_LOAD_TOOLS.md) beschrieben.

## Optionaler Snapshot-Test über Steam

Auf zwei Rechnern mit der bestätigten Zwei-Personen-Steam-Lobby aus dem
obigen Test bleiben beide RE2-Prozesse und Plugins offen. Für diesen
separaten Test ist auf beiden Rechnern die reguläre Python-Posen-Bridge
beendet, damit das Terminalwerkzeug die Pipe exklusiv verwendet. Alle
Befehle laufen im Repository des jeweiligen Rechners. Als Eingabe dient
ein synthetischer v1-Modellzustand. Der Host erstellt ihn im Arbeitsverzeichnis.

~~~powershell
@'
from pathlib import Path
from protocol import v1
from sync_model import Host

host = Host()
host.emit('enemy', 'example', {'observation': 'x' * 120000})
Path('snapshot-host.json').write_bytes(
    v1.encode({'version': 1, 'type': 'snapshot', 'data': host.snapshot()}))
'@ | python -
python steam_snapshot_transfer.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --file snapshot-host.json
~~~

Die Host-Ausgabe enthält die beiden Kennungen für den Gast. Der Gast
startet innerhalb von 30 Sekunden mit den angezeigten Werten.

~~~powershell
python steam_snapshot_transfer.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --file snapshot-guest.json --session-id HOST_SITZUNG --request-id HOST_ANFRAGE
~~~

Erwartet werden `Guest acknowledged the verified snapshot` am Host und
`Verified snapshot at sequence 1` beim Gast. Beide Dateien müssen per
`Get-FileHash -Algorithm SHA256` denselben Wert ergeben. Wird der Peer
während des Transfers getrennt, endet der Test mit Fehler und die Gastdatei
bleibt auf dem vorherigen Stand. Für einen Wiederholungsversuch wird der
Hostbefehl neu gestartet. Der Terminalmodus schreibt eine Modelldatei und
liest oder schreibt keinen RE2-Spielstand.

## Prüfumfang

Die Python-Tests prüfen die Datenpfade beider Rollen bis zur Gastdatei
mit einer lokalen Nachrichtenverbindung, Replays, fremde Spieler-IDs,
Sequenzlücken, Digest-Prüfung und Ausblenden beim Verbindungsverlust.
Der Prozess-Test deckt zusätzlich einen Host-Bridge-Neustart bei unverändertem
Steam-Peer und die Übernahme einer neuen Sitzungskennung nach `hello` ab.
Er prüft außerdem die Entfernung beider Posen durch sequenzierte Host-Events,
während die Verbindung bestehen bleibt.
Die Windows-Native-Probe verwendet RE2 Steam-Build 11636119 und REFramework
d1461375. In einer Solo-Lobby war die Pipe erreichbar und lehnte einen
Versand ohne bestätigten Peer ab. Der Steam-Datenpfad mit zwei Konten
und die Darstellung in einer zweiten RE2-Instanz stehen aus. Weil die
Anzeigefrist beim Empfang beginnt, muss eine künstlich verzögerte Steam-
Nachricht in zwei Instanzen noch auf sichtbare Bewegungsverzögerung geprüft
werden.
