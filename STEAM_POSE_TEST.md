# v1-Posenbridge über Steam prüfen

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
   werden.
2. Das Plugin nach [der Bauanleitung](network/steam_lobby_probe/README.md)
   installieren. In beide REFramework-`autorun`-Ordner
   `re2_coop_observer.lua` und `re2_coop_guest_pose.lua` kopieren.
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
   Drehung nacheinander in beiden Richtungen prüfen. Die animierte
   Darstellung kann separat gemäß #26 geprüft werden.
6. Die Gast-Lobby verlassen und prüfen, dass auf der Gegenseite die
   Pose verschwindet. Nach einem Neustart des Python-Hosts die Python-
   Bridge auf dem Gast ebenfalls neu starten. Der Gast nimmt während
   seiner Laufzeit ausschließlich Snapshots derselben Host-Sitzung an.

## Prüfumfang

Die Python-Tests prüfen die Datenpfade beider Rollen bis zur Gastdatei
mit einer lokalen Nachrichtenverbindung, Replays, fremde Spieler-IDs,
Sequenzlücken, Digest-Prüfung und Ausblenden beim Verbindungsverlust.
Die Windows-Native-Probe verwendet RE2 Steam-Build 11636119 und REFramework
d1461375. In einer Solo-Lobby war die Pipe erreichbar und lehnte einen
Versand ohne bestätigten Peer ab. Der Steam-Datenpfad mit zwei Konten
und die Darstellung in einer zweiten RE2-Instanz stehen aus. Weil die
Anzeigefrist beim Empfang beginnt, muss eine künstlich verzögerte Steam-
Nachricht in zwei Instanzen noch auf sichtbare Bewegungsverzögerung geprüft
werden.
