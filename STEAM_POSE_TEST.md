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

### Nativer Gegnerbericht als Hostquelle

In der isolierten Host-Testinstallation müssen der Gegnerleser aus #71
und der [lesende Ladebeleg](LOAD_WITNESS.md) mit Save-Guard und Katalog
laufen. Nach der abgesicherten alten-Slot-Lesung ersetzt am Host der
folgende Befehl die Variante mit `--file`. Die Werte stammen aus dem
bereits abgeschlossenen Ladeversuch.

~~~powershell
python steam_snapshot_transfer.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --native-enemies --load-request-id LADE_ID --save-slot scenario:4 --allow-save-date 2026-11-11
~~~

Für den GUID-Vergleich braucht der Gast dieselben Leser und seinen
eigenen abgesicherten Ladevorgang am selben Checkpoint. Seine Lade-ID
stammt von seinem Terminal. Die Sitzungs- und Anfrage-ID kommen weiterhin
vom Host.

~~~powershell
python steam_snapshot_transfer.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --file snapshot-guest.json --session-id HOST_SITZUNG --request-id HOST_ANFRAGE --native-enemies --load-request-id GAST_LADE_ID --save-slot scenario:4 --allow-save-date 2026-11-11
~~~

Beim ersten passenden Abruf liest der Host seine frischen Berichte. Der
Gast liest seine unmittelbar vor der Empfangsbestätigung. Die
Drei-Sekunden-Frische bezieht sich jeweils auf die lokale Uhr. Bei einem
anderen Checkpoint, abgelaufener Bestätigung oder fehlender Quelle bricht
der Gast ab und eine frühere Gastdatei bleibt erhalten.

Ein erfolgreicher Vergleich gibt einen JSON-Bericht aus und speichert den
geprüften Host-Snapshot. `sources` enthält je Quelle die Trefferzahl und
die GUIDs für einseitige Einträge oder abweichende Typ-/InheritIDs.
`live_candidates` enthält nur passende GUIDs mit aktivem Controller auf
beiden Seiten. Ein Vergleich mit Abweichungen liefert ebenfalls den
Befund. Die Beobachtung gehört zum geladenen Checkpoint. Für eine Messung
im selben Raum bleiben beide Figuren nach dem Laden an der Ausgangsposition.

### Laufende Gegnerbeobachtung an einem Host

Mit demselben abgesicherten Ladeversuch und den beiden nativen Lesern
kann ein lokaler v1-Host HP und Todesflags fortlaufend veröffentlichen.
Der erste Befehl gibt die lokale Portnummer aus. Ein zweites Terminal verwendet
diese Portnummer und übernimmt die veröffentlichten Zustände.

~~~powershell
python enemy_live.py --data "PFAD-ZU-RE2/reframework/data" --load-request-id LADE_ID --save-slot scenario:4 --allow-save-date 2026-11-11 --seconds 30
python wire.py client --port HOST_PORT --protocol-version 1 --listen --events 0
~~~

Die Diagnose lauscht auf `127.0.0.1`. Sie lässt sich in derselben bereits
freigegebenen Spielszene ausführen, während sich ein Gegnerzustand ändert.
Der Client prüft die v1-Digests und gibt beim Ende den letzten bestätigten
Modellzustand aus. Der aktuelle Befund steht unter
`state.flags.native_enemy_live`. Für einen einzelnen Folgezustand kann
der Client auch mit `--events 1` lauschen.

Erwartet werden beobachtete HP, getrennte native Lebens-/Todesflags und
die GUID bei einem aktiven Controller. Sobald kein aktiver Controller
mehr beobachtet wird, entfällt der Eintrag. Bei Quellenverlust wird der
Befund unverfügbar. Die Diagnose überträgt keine Änderungen an das Spiel.

### Laufende Gegnerbeobachtung über Steam

Beide Rollen ergänzen die Befehle aus dem nativen Snapshot-Test um
`--live-updates 20`. Beide verwenden dieselbe Anzahl. Nach dem bestätigten
Checkpoint und dem gespeicherten Host-Snapshot ruft der Gast die aktive
Gegnermenge in derselben Steam-Verbindung ab. Die erste JSON-Zeile meldet
wie zuvor den GUID-Abgleich. Danach zeigt jede JSON-Zeile einen geänderten
Live-Befund. Bei unveränderter Host-Beobachtung kann sich der Gastbefund
weiterhin ändern, wenn die passenden lokalen Controller wechseln.

Der Gast gibt die Host-HP ausschließlich für gerade auf beiden Seiten
beobachtete aktive GUIDs mit gleichem Typ und gleicher InheritID aus.
Quellenverlust leert den Befund. Das Ende des Tests erzeugt eine
abschließende Zeile mit `available:false`. Die über `--file` gespeicherte
Datei enthält weiterhin den ersten vollständigen Host-Snapshot.
Ein Wechsel der Steam-Pipe-Epoche beendet den Test. Für einen neuen
Versuch beide Befehle mit der neu ausgegebenen Anfrage starten.

### Gegnerwerte im REFramework-Gast lesen

Für den Gast die optionale Diagnose
`reframework/diagnostics/re2_coop_guest_enemy_probe.lua` in den lokalen
`reframework/autorun`-Ordner kopieren. Zusätzlich zu `--live-updates`
verwendet nur der Gast `--export-live-enemies`. Der Hostbefehl bleibt
derselbe. Die bereits verwendeten nativen Leser und der Save-Guard laufen
weiter. Die Diagnose ist für RE2 mit TDB 70 vorgesehen.

Während des Testlaufs die lokale Rücklesedatei abfragen.

~~~powershell
Get-Content -LiteralPath "PFAD-ZU-RE2/reframework/data/re2_coop_guest_enemy_readback.json" -Raw | ConvertFrom-Json
~~~

Ein verfügbarer Befund enthält `state.eligible`, `state.skipped` und
je passender aktiver GUID `host_hp`, `local_hp` sowie die jeweiligen
nativen Todesflags. Eine geänderte lokale Zuordnung reduziert die
passende Menge. Bei Quellenverlust, Ablauf oder beendetem Abruf ist
`available:false`. Die Diagnose schreibt ausschließlich ihren
Rücklesebefund.

Der isolierte Test mit RE2-Build 11636119 und REFramework d1461375
erkannte am echten Titelbild den Dateiexport, die fehlende lokale Szene
und den Ablauf des Belegs. Der Guard meldete null Lade- und
Schreibaufrufe. Positive Zuordnung und die Anwendung von Werten im
Kampf müssen in den echten Spielinstanzen geprüft werden.

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
