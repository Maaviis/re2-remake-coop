# v1-Posenbridge �ber Steam pr�fen

Dieser Entwurf verbindet die beiden best�tigten Teilnehmer einer privaten
RE2-Koop-Lobby mit der vorhandenen v1-Posenbridge. Steam transportiert JSON-
Nachrichten mit maximal 4096 Byte auf einem eigenen zuverl�ssigen Kanal.
Eine lokale Windows-Pipe verbindet das REFramework-Plugin mit Python.
Der Host beh�lt die Autorit�t �ber Sitzung, Sequenz und Zustandsdigest.
Der Gast kann ausschlie�lich seine konfigurierte Spielerpose vorschlagen.

## Test auf zwei Rechnern

1. Auf beiden Rechnern dasselbe Commit und denselben unterst�tzten RE2-Build
   verwenden. Jede Bridge pr�ft ihre lokale Observer-Probe gegen die eigene
   Uhr. Der Steam-Pfad beginnt die f�nfsek�ndige Anzeigefrist beim Empfang
   auf dem jeweiligen Rechner; die Systemuhren m�ssen daf�r nicht abgeglichen
   werden. Der Host entfernt abgelaufene Posen mit einem sequenzierten
   v1-Event aus seinem verbindlichen Zustand. Ein sp�terer Snapshot enth�lt
   dann keinen alten Transform oder Clip. Pro Spieler sperrt der Host bis zu
   256 abgel�ste Observer-L�ufe gegen versp�tete Nachrichten; am Limit sind
   weitere Laufwechsel erst in einer neuen Host-Sitzung m�glich.
2. Das Plugin nach [der Bauanleitung](network/steam_lobby_probe/README.md)
   installieren. In beide REFramework-`autorun`-Ordner
   `re2_coop_observer.lua` und `re2_coop_guest_pose.lua` kopieren.
   F�r den optionalen Animationsvergleich zus�tzlich
   `re2_coop_remote_motion.lua` in den Gast-`autorun`-Ordner kopieren.
   Die beiden Rechner verwenden eigene REFramework-Datenordner.
3. Der Host erstellt die Steam-Lobby und l�dt das vereinbarte Gastkonto ein.
   Der Gast nimmt die Einladung an und f�hrt `join-invite` aus.
   Mit `peer-status` und `ping` vorher in beiden Richtungen pr�fen,
   ob der jeweilige Peer tats�chlich antwortet.
4. Im Repository-Verzeichnis die jeweilige Bridge starten. Rollen und beide
   Spieler-IDs m�ssen auf beiden Rechnern �bereinstimmen. Pro Datenordner
   l�uft eine Bridge. `--pid` erh�lt die PID des jeweiligen RE2-Prozesses.

~~~powershell
$re2Pid = (Get-Process -Name re2).Id
python steam_pose_bridge.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data"
# Auf dem Gastrechner:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data"
~~~

5. In beiden Instanzen denselben Kampagnenraum laden. Die Diagnoseanzeige
   `RE2 Coop - remote pose` zeigt jeweils die Gegenstelle. Position und
   Drehung nacheinander in beiden Richtungen pr�fen. Bei Host Leon und Gast
   Claire den beobachteten Leon-Idle-Clip abwarten. Auf dem Gast kann dann
   `pwsh -File scripts/motion_probe.ps1 -Action Start -DataDirectory
   "PFAD-ZU-RE2/reframework/data"` die optionale animierte Darstellung
   einschalten. Im REFramework-Log `RE2_COOP_MOTION_PLAYBACK` auf Clipname,
   Phasen-Readback und sp�tere Entfernung pr�fen. Die relative Phase ist
   experimentell und noch nicht mit zwei echten Spielinstanzen gemessen.
6. Die Python-Host-Bridge beenden, w�hrend die Steam-Lobby bestehen bleibt.
   Die Gastpose muss nach dem Timeout verschwinden. Die Host-Bridge neu
   starten und pr�fen, dass die laufende Gast-Bridge nach einem neuen
   `hello` automatisch die neue Host-Sitzung �bernimmt. Sitzungskennung und
   Pose auf beiden Seiten vergleichen. Der Gast darf nur den Snapshot mit
   der Kennung seiner aktuellen Anfrage und g�ltigem Digest �bernehmen.
   Der neue Host verwirft Posen-Vorschl�ge mit der alten Sitzungskennung.
   Danach die Gast-Lobby verlassen;
   auf der Gegenseite muss die Pose wieder verschwinden.

## Pr�fumfang

Die Python-Tests pr�fen die Datenpfade beider Rollen bis zur Gastdatei
mit einer lokalen Nachrichtenverbindung, Replays, fremde Spieler-IDs,
Sequenzl�cken, Digest-Pr�fung und Ausblenden beim Verbindungsverlust.
Der Prozess-Test deckt zus�tzlich einen Host-Bridge-Neustart bei unver�ndertem
Steam-Peer und die �bernahme einer neuen Sitzungskennung nach `hello` ab.
Er pr�ft au�erdem die Entfernung beider Posen durch sequenzierte Host-Events,
w�hrend die Verbindung bestehen bleibt.
Die Windows-Native-Probe verwendet RE2 Steam-Build 11636119 und REFramework
d1461375. In einer Solo-Lobby war die Pipe erreichbar und lehnte einen
Versand ohne best�tigten Peer ab. Der Steam-Datenpfad mit zwei Konten
und die Darstellung in einer zweiten RE2-Instanz stehen aus. Weil die
Anzeigefrist beim Empfang beginnt, muss eine k�nstlich verz�gerte Steam-
Nachricht in zwei Instanzen noch auf sichtbare Bewegungsverz�gerung gepr�ft
werden.
