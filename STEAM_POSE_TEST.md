# v1-Posenbridge über Steam prüfen

Der optionale Austausch von Lobby-Auswahl und Bereitschaft ist in
[LOBBY_TEST.md](LOBBY_TEST.md) beschrieben.

Dieser Entwurf verbindet die beiden bestätigten Teilnehmer einer privaten
RE2-Koop-Lobby mit der vorhandenen v1-Posenbridge. Steam transportiert JSON-
Nachrichten mit maximal 4096 Byte auf einem eigenen zuverlässigen Kanal.
Eine lokale Windows-Pipe verbindet das REFramework-Plugin mit Python.
Der Host behält die Autorität über Sitzung, Sequenz und Zustandsdigest.
Der Gast kann ausschließlich seine konfigurierte Spielerpose vorschlagen.

Der Host sendet die bestätigten Ereignisse für beide Spieler im selben
Posenkanal. Die Bridge holt wartende Nachrichten ohne zusätzliche Pause und
in ihrer ursprünglichen Reihenfolge ab. Das lokale Plugin liefert bis zu vier
Posenkanal-Nachrichten pro Pipe-Antwort, begrenzt auf die bisherigen 4105 Byte.
Volle Einzelframes passen weiterhin in die Einzelnachricht. Bei einer älteren
Plugin-Version verwendet die Bridge einzelne Abfragen. Bei leerem Kanal oder
einem Lesefehler wartet sie zwischen den Abfragen. Die Regression simuliert
zehn Beobachtungen pro Sekunde auf jeder Seite.

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
3. Im Repository-Verzeichnis auf beiden Rechnern Spiel und Bridge mit
   der passenden Rolle starten. Pro Datenordner läuft eine Bridge. Sie
   veröffentlicht den Status für den ausgewählten Spielprozess und
   beendet sich, wenn dieser Prozess endet.
4. Der Host erstellt die Steam-Lobby und lädt das vereinbarte Gastkonto ein.
   Der Gast nimmt die Einladung an und führt `join-invite` aus.
   Mit `peer-status` und `ping` vorher in beiden Richtungen prüfen,
   ob der jeweilige Peer tatsächlich antwortet.

~~~powershell
pwsh -File scripts/start_steam_coop.ps1 -GameDirectory "PFAD-ZU-RE2" -Role host
# Auf dem Gastrechner:
pwsh -File scripts/start_steam_coop.ps1 -GameDirectory "PFAD-ZU-RE2" -Role guest
~~~

Für den Gasttest mit beendetem RE2 den Launcher mit `-WaitForInvite`
starten, dann die Einladung in Steam öffnen. Die Gast-Bridge startet,
sobald RE2 die Einladung als `invite-pending` meldet. Danach im
Multiplayer-Menü **Steam-Einladung annehmen** wählen. Für das Zeitfenster
ist `-InviteWaitSeconds` verfügbar, mit 300 Sekunden als Vorgabe.

~~~powershell
pwsh -File scripts/start_steam_coop.ps1 -GameDirectory "PFAD-ZU-RE2" -WaitForInvite
~~~

Im Einzelinstanz-Test blieb der Launcher bei einem normalen RE2-Start
im Wartemodus. Nach dem Schließen startete Steam RE2 mit einer
synthetischen Starteinladung. Der Launcher verband die Gast-Bridge mit
der neuen PID. Sie meldete die Einladung zur Bestätigung und beendete
sich mit der Spielinstanz.

5. In beiden Instanzen denselben Kampagnenraum laden. Die Diagnoseanzeige
   `RE2 Coop - remote pose` zeigt jeweils die Gegenstelle. Position und
   Drehung nacheinander in beiden Richtungen prüfen. Der Terminalbefehl
   unten aktiviert auf jedem Rechner die Schaufensterpuppe für die
   empfangene Pose. Im REFramework-Log `RE2_COOP_GUEST_OBJECT verified`
   mit `mannequin resources assigned` und veränderten Positionen und
   Drehungen suchen. Bei Host Leon und Gast Claire den beobachteten
   Leon-Idle-Clip abwarten. Auf dem Gast kann dann
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

7. Die Steam-Lobby auch auf dem Host verlassen und eine neue erstellen,
   während RE2 und die Host-Bridge weiterlaufen. Mit dem Plugin aus #70
   muss die neue Steam-Mitgliedschaft eine neue v1-Sitzungskennung
   erhalten. Eine erneute Verbindung innerhalb derselben Steam-Lobby
   behält die Sitzungskennung. Die Host-Auswahl bleibt beim Neuanlegen
   erhalten. Beide Seiten müssen ihre Bereitschaft und die Dateivorprüfung
   für die neue Sitzung erneut bestätigen.

~~~powershell
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" pose-probe start
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" pose-probe stop
~~~

`start` erst im geladenen Kampagnenraum aufrufen. Das Skript wartet dann
auf eine gültige Gegenstellenpose. Bei Ablauf, Trennung, Szenenwechsel oder
`stop` wird das eigene Testobjekt entfernt. Für den Abnahmeschritt „Gast
verlässt die Lobby“ die Puppe auf dem Host bis zum Verschwinden aktiv
lassen. Die Protokollzeile bestätigt den Engine-Transform und die
zugewiesenen Render-Ressourcen. Sichtbarkeit prüfen beide Spieler im Spiel.

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

Mit dem Launcher bestand der Menücheck in der installierten RE2-Fassung
(Steam-Build 11636119) nacheinander als Host und Gast. Die Bridge
veröffentlichte jeweils einen frischen Status und beendete sich mit dem
Spiel. Beim Host bestätigte die gestartete Bridge außerdem das Erstellen
und Verlassen einer privaten Lobby ohne zweites Mitglied.

In RE2 Steam-Build 11636119 mit REFramework d1461375 bestand der Menücheck
in einer isolierten Instanz nacheinander für die Host-Bridge im Zustand
`idle` und mit privater Solo-Lobby (`owned`) sowie für die Gast-Bridge in
`idle`. Eine vertauschte Rolle lieferte `wrong-role`. Die Solo-Lobby wurde
per Terminal erstellt und verlassen. Einladung und Datenaustausch über
zwei Steam-Konten bleiben offen.

## Steam-Verbindung im Hauptmenü abnehmen

Für den ersten gemeinsamen Lauf im Hauptmenü bleiben. Nach Annahme der
Einladung meldet der Host `owned` und der Gast `joined`. Beide prüfen den
Roundtrip und die Bridge für ihre jeweilige Rolle. Auf der Gastseite
`--role guest` einsetzen.

~~~powershell
.\network\steam_lobby_probe\lobby.ps1 -GameProcessId $re2Pid -Command ping
.\network\steam_lobby_probe\lobby.ps1 -GameProcessId $re2Pid -Command peer-status
python -B steam_pose_preflight.py --stage link --game "PFAD-ZU-RE2" --dll "PFAD-ZUM-TESTBUILD/re2_coop_steam_lobby_probe.dll" --pid $re2Pid --role host
~~~

Den letzten Befehl nach `peer-round-trip-verified` ausführen. `ready` muss
auf beiden Seiten wahr sein. `session_fingerprint` muss übereinstimmen.
Der Bericht vergleicht die aktuelle native Mitgliedschaft mit der vom
lokalen Bridge-Prozess zuletzt gemeldeten Revision. Bei einem frischen
Beitritt kann diese Meldung kurz nachlaufen. Im Fehlerfall `checks`
festhalten und nach der nächsten Statusaktualisierung erneut prüfen.

## Spielerpose im Kampagnenraum prüfen

Nach Abnahme des isolierten Speicherschutzes, dem Lobbybeitritt und einem
erfolgreichen `ping` auf dieser Seite den Kampagnenraum laden und den
lokalen Stand prüfen. Der Check benötigt Windows,
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
obigen Test bleiben beide RE2-Prozesse und Plugins offen. Ohne zusätzliche
Option beenden beide Rechner vor diesem Test die reguläre
Python-Posen-Bridge, damit das Terminalwerkzeug ihre Pipe exklusiv verwendet.
Alle Befehle laufen im Repository des jeweiligen Rechners. Als Eingabe
dient ein synthetischer v1-Modellzustand. Der Host erstellt ihn im
Arbeitsverzeichnis.

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

### Posen und Gegner gleichzeitig übertragen

Beide Installationen verwenden einen Plugin-Build mit der Snapshot-Pipe.
Die reguläre Posen-Bridge läuft auf beiden Seiten wie oben beschrieben
weiter. Host und Gast ergänzen ihre Snapshot-Befehle jeweils um
`--snapshot-pipe`. Beide Werkzeuge verwenden dieselbe Prozess-ID und
denselben lokalen REFramework-Datenordner auf ihrer Seite. Die Snapshot-
Bridge sperrt eine eigene Datei und liest ausschließlich ihre eigene Pipe.
Das gilt auch für `--native-enemies` und `--live-updates`.

Der integrierte Windows-Build wurde mit einer echten RE2-Instanz auf
Steam-Build 11636119 geprüft. Der Terminaltest legte eine private Lobby
an, bestätigte `owned` und `peer-waiting-for-member` und fragte beide
nativen Pipes parallel je fünfmal ab. Beide meldeten in allen Abfragen
den fehlenden Peer. Nach `leave` meldete die Lobby wieder `idle`.
Der Test lud keinen Spielstand. Nach der Wiederherstellung der
Originalinstallation stimmten alle 23 erfassten Spielstand-Hashes überein.

Für die Abnahme in derselben Szene beide Figuren während des Transfers
bewegen. Die sichtbare Darstellung und die bestätigten Posen in beiden
Richtungen prüfen. Der Gast prüft zusätzlich den Snapshot oder bei
`--live-updates` den aktualisierten Gegnerbefund. Danach nur den
Snapshot-Abruf beenden und die Posen weiter beobachten. Ein Wechsel
des Steam-Lobbypeers setzt beide Streams zurück.

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

Nach der ersten bestätigten Ladebindung endet der Livebeobachter nicht
allein wegen eines Ladealters über 120 Sekunden. Guard, beide native
Quellen und Gastempfang bleiben jeweils fristgebunden. Ein neuer
Beobachter braucht weiterhin seine gültige Erstprüfung. Details und
Prüfgrenzen stehen in [LIVE_LOAD_CONTINUITY.md](LIVE_LOAD_CONTINUITY.md).

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

Für die Todesdiagnose ergänzen beide Rollen `--death-evidence`. Dann
erscheinen beobachtete native `is_dead:true`-Werte unter `death_observations`
mit der Quellsequenz. Prüfen, dass die GUID dort erhalten bleibt, wenn
ihr Controller aus `enemies` verschwindet. Eine GUID mit null HP und
`is_dead:false` darf dabei keinen Todesbefund liefern. Bei neuen
Hostproben nach Ablauf der Frist oder bei Quellenverlust entfällt der
Befund.

### Gegnerwerte im REFramework-Gast lesen

Für den Gast die optionale Diagnose
`reframework/diagnostics/re2_coop_guest_enemy_probe.lua` in den lokalen
`reframework/autorun`-Ordner kopieren und ihr Modul
`reframework/autorun/re2_coop/guest_enemy_readback.lua` installieren.
Zusätzlich zu `--live-updates` verwendet nur der Gast
`--export-live-enemies`. Der Hostbefehl bleibt
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

Mit `--death-evidence` auf beiden Seiten steht der Host-Befund unter
`state.host_death_observations`, solange der Gast den lokalen Ladebeleg
bestätigen kann. Prüfen, dass eine dort sichtbare GUID ohne aktiven
Hostcontroller keinen Eintrag unter `state.enemies` erhält.

Der isolierte Test mit RE2-Build 11636119 und REFramework d1461375
erkannte am echten Titelbild den Dateiexport, die fehlende lokale Szene
und den Ablauf des Belegs. Der Guard meldete null Lade- und
Schreibaufrufe. Positive Zuordnung und die Anwendung von Werten im
Kampf müssen in den echten Spielinstanzen geprüft werden.

### Positive Gegner-HP im isolierten Gast anwenden

Für den ausdrücklichen Schreibtest am Gast
`reframework/diagnostics/re2_coop_guest_enemy_hp_apply.lua` als
Autorun-Diagnose installieren. Dazu die Module
`guest_enemy_readback.lua`, `guest_enemy_hp.lua` und den Leser
`enemy_state.lua` aus #71 unter `reframework/autorun/re2_coop`
bereitstellen. Die beiden Terminals verwenden weiterhin
`--native-enemies --live-updates 20`, der Gast zusätzlich
`--export-live-enemies`. Beide lesen in ihren isolierten,
abgesicherten Installationen denselben zuvor freigegebenen Checkpoint.

Nach einer messbaren positiven HP-Änderung am Host den Gastbefund
`re2_coop_guest_enemy_readback.json` prüfen. Bei übereinstimmenden aktiven
Gegnern sollte `state.application.applied` die Anzahl bestätigter
Schreibvorgänge melden. `identical` zählt passende bereits gleiche HP.
Für einen einzelnen Aufruf muss der positive Zielwert innerhalb der auf
beiden Seiten gleichen Standard-HP liegen. Tote, inaktive und gegen
Schaden geschützte Controller werden übergangen. Die Anwendung prüft den
aktuellen Gegner samt Checkpoint erneut und liest den geschriebenen
Wert am selben Controller zurück. Der nächste lokale Befund zeigt die
nachgemessenen Gast-HP. Bei einem fehlgeschlagenen Rücklesen sperrt der
Adapter die weiteren Schreibvorgänge bis zum Lua-Neuladen.

Ein kurzzeitig unlesbarer nativer Zustand, eine wechselnde aktive Menge
oder ein noch geschützter Gegner verbraucht den Hostbefund nicht. Erst
nach erneutem vollständigem Belegvergleich darf derselbe unveränderte
Hostbefund angewendet werden. Ein bereits geschriebener oder als gleich
bestätigter Gegner wird innerhalb dieser Beobachtung nicht erneut
angewendet; andere später passende Gegner bleiben prüfbar. Ältere
Beobachtungen bleiben gesperrt. Der bestehende Dateileser muss bei jedem
Versuch weiterhin Frist, Ladebeleg und lokale Zuordnung bestätigen;
diese Korrektur verlängert keine Frist. Läuft die Freigabe unmittelbar
vor einem Schreibversuch ab, bleibt dieser Gegner für einen später
erneuerten Empfangsbeleg erneut prüfbar. Die Erholungsfälle sind bisher
mit simulierten Lua-Quellen geprüft und im Zwei-Instanzen-Lauf gesondert
nachzuweisen.

Für die Abnahme den letzten bestätigten Schreibbefund abfragen.

~~~powershell
(Get-Content -LiteralPath "PFAD-ZU-RE2/reframework/data/re2_coop_guest_enemy_readback.json" -Raw | ConvertFrom-Json).last_application
~~~

Dieser Befund bleibt nach wiederholten Abrufen oder dem Ende des
Gaststreams lesbar. Sitzung, Empfangssequenz und Host-Quellsequenz
ordnen ihn dem tatsächlichen Vorgang zu. `before_hp` wurde vor dem
Setter gelesen und `after_hp` danach direkt an derselben Komponente.
Wenn dieselbe Host-Probe mehrere Gegner betrifft, enthält der Befund
alle bestätigten GUIDs, auch wenn sie mit verschiedenen Gastabrufen
erst nacheinander verfügbar werden. Pro GUID geben `receipt_sequence`
und `applied_at` den eigenen Schreibvorgang an. Der Nachweis bleibt
auch bei einem späteren Fehler lesbar.
Ein leerer Livezustand mit `available:false` beendet die Gültigkeit
der laufenden Beobachtung.

Der Titelbildversuch auf Build 11636119 und REFramework d1461375 bestätigte
am eigenen Testobjekt ein natives HP-Rücklesen von 70 auf 37 mit
Standard-HP 100. Wince und Todesflag blieben gleich. Der Aufruf zur
Entfernung des Testobjekts war erfolgreich. Ein separater Titelbildlauf bestätigte,
dass die fertige Autorun-Diagnose verfügbar ist und ohne Gastbeleg
inaktiv bleibt. Der Guard verzeichnete jeweils null Lade-/Schreibaufrufe.
Der echte Test am Kampagnengegner in zwei Steam-Instanzen steht aus.

Ein weiterer isolierter Titelbildlauf prüfte vier eigene
`EnemyHitPointController`-Komponenten. Jede startete mit
70 aktuellen und 100 Standard-HP, falschem Todesflag, 30 nativen
Schadenspunkten und Wince 0. Die Probe setzte oder änderte jede
Komponente genau einmal und fragte die Getter danach erneut ab.

| Nativer Aufruf | HP danach | Todesflag danach | Schadenspunkte danach | Wince danach |
| --- | ---: | --- | ---: | ---: |
| `set_CurrentHitPoint(0)` | 0 | wahr | 100 | 0 |
| `addDamage(33)` | 37 | falsch | 63 | 0 |
| `addDamage(70)` | 0 | wahr | 100 | 0 |
| `HitPointController.dead()` | 0 | wahr | 100 | 0 |

Die vier Aufrufe zur Entfernung der eigenen Testobjekte waren
erfolgreich. Der Save-Guard sah null Lade- und Schreibaufrufe. Alle
23 Spielstand-Hashes blieben unverändert. Für Kampagnengegner müssen
Aktionswechsel, Eliminierung, Kill-Zähler und Skriptfortschritt im
Laufzeittest separat beobachtet werden.

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
