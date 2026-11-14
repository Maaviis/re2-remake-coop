# Lobby-Auswahl und Bereitschaft über Steam

Der optionale Lobby-Pfad verbindet das Host-Modell aus #24/#27 mit der
Steam-Posenbridge. Er überträgt Slotkennung, Einstellungen und Bereitschaft
über denselben bestätigten Steam-Peer wie die Posen. Für beide Rechner
dieselbe Bridge-Fassung verwenden und die Steam-Lobby zuerst nach
[STEAM_POSE_TEST.md](STEAM_POSE_TEST.md) erstellen beziehungsweise betreten.

## Terminalbedienung

Die Host-Bridge kann bereits vor dem Gastbeitritt gestartet werden:

~~~powershell
$re2Pid = (Get-Process -Name re2).Id
python steam_pose_bridge.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby --lobby-save-slot "slot-1"
# Auf dem Gastrechner:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby
~~~

In einem zweiten Terminal auf jeder Seite den lokalen Status prüfen:

~~~powershell
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" status
~~~

Nur der Host kann die Slotkennung und Einstellungen ändern. Das folgende
Beispiel setzt den Slot und ergänzt beziehungsweise ändert Einstellungen:

~~~powershell
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" configure --save-slot "slot-2" --settings '{"campaign":"leon","difficulty":"standard"}'
~~~

Nach der Verbindung auf beiden Rechnern Bereitschaft melden:

~~~powershell
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" ready yes
# Zurücknehmen:
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" ready no
~~~

Der Befehl bestätigt nur das Schreiben der lokalen Anweisung. Den
autoritativen Ausgang anschließend mit `status` prüfen. `fresh` muss wahr
sein. `connected` beschreibt den geprüften Bridge-Link; `lobby.data.ready`
enthält die vom Host akzeptierte Bereitschaft. `error` nennt einen
abgewiesenen lokalen Befehl. Bei Auswahländerung oder Wiederbeitritt müssen
beide Teilnehmer ihre Bereitschaft für die neue Revision erneut melden.

## Grenzen und Abnahme

Die Slotkennung und Einstellungen sind Metadaten. Dieser Pfad liest oder
lädt keine RE2-Speicherstände und startet keine Kampagne. Die Bridge darf
daher nicht als spielbereites Koop-Menü bezeichnet werden. Die Darstellung
im Stil des Originalmenüs, echte Slotprüfung und Engine-Anbindung bleiben
offen. Die Posen-Diagnose läuft unabhängig von der Lobby-Bereitschaft.

Der automatisierte Test verwendet zwei Bridge-Schleifen, getrennte
Datenordner und einen simulierten Nachrichtenlink. Er prüft gleiche
Auswahl, Host-Rechte, Bereitschaft, Host-Neustart und Rücksetzen der
Bereitschaft. Zusätzlich werden veraltete Revisionen, alte Sitzungen,
Digestfehler und Sequenzrücksprünge geprüft. Ein neuer Handshake setzt
Bereitschaft auch zurück, wenn der Host noch keinen Timeout erkannt hat.

Mit zwei echten Steam-Konten bleiben nachzuweisen: Einladung und Beitritt,
gleiche Slotkennung und Einstellungen, Bereitschaft auf beiden Seiten,
Änderung einer Auswahl bei bestehender Bereitschaft, kurzer Gastabbruch
und Wiederbeitritt sowie Host-Bridge-Neustart. Jeweils Sitzungskennung,
Lobby-Sequenz, Revision und beide Bereitschaftswerte vergleichen.
Speicherdateien und Kontokennungen nicht veröffentlichen.
