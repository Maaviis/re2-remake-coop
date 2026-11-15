# Lobby-Auswahl und Bereitschaft über Steam

Der noch nicht visuell abgenommene Menüentwurf und die neue
Einladungsanforderung sind in [LOBBY_MENU.md](LOBBY_MENU.md) beschrieben.

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

Die Auswahl bleibt Metadaten; die Bridge lädt keinen RE2-Spielstand und
startet keine Kampagne. Mit dem optionalen [nativen Katalog](SAVE_CATALOG.md)
prüft der Host die Auswahl gegen die bestehende Szenario-Tabelle und
einen gegebenenfalls gesetzten Datumsfilter. Die sichtbare Host-Auswahl
wurde am Titelbild in 1920x1080 nativ geprüft; weitere Ansichten und die
echte Ladeanbindung bleiben offen. Die Posen-Diagnose läuft unabhängig von
der Lobby-Bereitschaft.

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

## Nativer Einzelinstanz-Test am 14. November 2026

RE2 Steam-Build 11636119 wurde über Steam aus dem Terminal gestartet,
ohne einen Kampagnenspielstand zu laden. Das Steam-Plugin aus #42 wurde
mit MSVC 19.44 als Windows-x64-Release gebaut; beide nativen CTests
bestanden. Die festgelegten REFramework- und Valve-Header entsprechen
der Bauanleitung des Plugins.

Steam bestätigte eine private Host-Lobby mit einem Mitglied. Die neue
Python-Bridge erreichte die echte RE2-Pipe, veröffentlichte den wartenden
Host und übernahm eine Auswahländerung samt höherer Lobby-Revision.
Ein Bereitschaftsbefehl ohne bestätigten Gast wurde abgelehnt. Das
beweist den lokalen Warte- und Bedienpfad, noch keinen Steam-Austausch
zwischen zwei Rechnern.

Danach wurde die Lobby verlassen, RE2 beendet und die nur für diesen
Test installierte Plugin-DLL entfernt. Die SHA-256-Prüfsummen aller zwölf
vor dem Start erfassten Dateien im Steam-Spielstandordner blieben gleich;
es kamen keine Dateien hinzu.
