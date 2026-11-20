# Lobby-Auswahl und Bereitschaft über Steam

Der noch nicht visuell abgenommene Menüentwurf und die neue
Einladungsanforderung sind in [LOBBY_MENU.md](LOBBY_MENU.md) beschrieben.

Der optionale Lobby-Pfad verbindet das Host-Modell aus #24/#27 mit der
Steam-Posenbridge. Er überträgt Slotkennung, Einstellungen und Bereitschaft
über denselben bestätigten Steam-Peer wie die Posen. Für beide Rechner
dieselbe Bridge-Fassung und das Plugin aus
[STEAM_POSE_TEST.md](STEAM_POSE_TEST.md) verwenden.

## Terminalbedienung

Die Host-Bridge kann bereits vor der Steam-Lobby gestartet werden:

~~~powershell
$re2Pid = (Get-Process -Name re2).Id
python steam_pose_bridge.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby --lobby-save-slot "slot-1"
# Auf dem Gastrechner:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby
~~~

Am Host **Multiplayer** und **Private Steam-Lobby erstellen** wählen oder
mit `python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" create`
dieselbe Anweisung im Terminal auslösen. `steam_lobby: "owned"` im lokalen
Status bestätigt die Erstellung durch Steam. Über **Spieler über Steam
einladen** ruft der Host den Steam-Dialog auf. Wenn Steam oder die eigene
Lobby dafür fehlen, zeigt das Menü den Fehler des Plugins an. Der Host
wählt den Kontakt im Steam-Overlay. Der Gast öffnet die Einladung in Steam
und bestätigt sie danach unter **Multiplayer** mit
**Steam-Einladung annehmen**. Dieselbe Aktion ist im Terminal als
`lobby_control.py --data "PFAD-ZU-RE2/reframework/data" join-invite`
verfügbar. Beide Wege benötigen die laufende Gast-Bridge und das neu
gebaute Plugin. `steam_lobby: "joined"` meldet die geprüfte
Steam-Mitgliedschaft. Die v1-Verbindung wird anschließend separat als
`connected: true` gemeldet.

Lehnt Steam den Beitritt ab, erscheint der Grund zur bestätigten Einladung
im Menü und im lokalen `error`-Feld. Bei einer geschlossenen Lobby meldet
die Bridge beispielsweise `Steam lobby no longer exists`.

Mit **Steam-Lobby verlassen** oder
`lobby_control.py --data "PFAD-ZU-RE2/reframework/data" leave`
beenden Host oder Gast ihre eigene bestätigte Steam-Mitgliedschaft.
Der Gast kann das auch tun, solange die v1-Verbindung noch auf den Host
wartet. Wenn der Posenkanal neu aufgebaut wird, fragt die Bridge den
Steam-Status sofort ab und veröffentlicht die bestätigte Mitgliedschaft
vor der ersten Pose. Ein Ausfall des Posenkanals allein hebt die
bestätigte Steam-Mitgliedschaft im lokalen Menü nicht auf.
Nach `steam_lobby: "idle"` kann derselbe Prozess eine neue Lobby
erstellen oder eine neue Einladung annehmen.

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

Die zusätzlich aktivierbare [gemeinsame Dateivorprüfung](SHARED_LOAD.md)
vergleicht die lokalen Bytes der ausgewählten Speicherdatei und bindet
Bestätigungen an Sitzung, Revision und Versuch. Sie ergänzt den
Metadatenverweis, löst aber ebenfalls keinen nativen Ladevorgang aus.

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

## Lobby-Erstellung über die Menü-Bridge am 15. November 2026

Mit RE2-Build 11636119 und REFramework d1461375 wechselte der neue,
lokale Status `steam_lobby` über `idle`, `creating` und `owned`.
Das Plugin protokollierte App-ID 883710, den lokalen Nutzer als
Eigentümer, ein Mitglied und zwei Plätze. Ein zweiter Erstellungsbefehl
im Zustand `owned` wurde abgewiesen. `lobby.ps1 leave` setzte den
Status zurück auf `idle`. Die 23 erfassten Steam-Dateien behielten ihre
SHA-256-Prüfsummen.

Der Einzelinstanz-Lauf löste die gemeinsame Anweisung über
`lobby_control.py create` aus. Die Auswahl per Menübutton und der
Wechsel zum Einladungsbutton sind im Lua-Test abgedeckt. Ein Klick im
laufenden RE2 und der Beitritt von einem zweiten Konto bleiben offen.

Mit derselben RE2- und REFramework-Version erreichte auch der neue
Gastpfad die echte Steam-API. Eine synthetische Starteinladung erschien
als `invite-pending`. Das Plugin lehnte eine andere Angebotsrevision
ab. Die Bestätigung per `lobby_control.py join-invite` löste genau einen
Beitrittsversuch aus. Steam lehnte die fehlende Lobby mit Resultat 2 ab.
Die Bridge meldete den Fehler und kehrte zu `idle` zurück. Die
Menüaktion ist im Lua-Test geprüft. Ein erfolgreicher Beitritt über eine
echte Einladung benötigt zwei Steam-Konten.

Auf demselben RE2-Build wurden in einem Prozess zwei private Host-Lobbys
nacheinander per Bridge-Befehl erstellt und verlassen. Das Plugin wies
zwischenzeitlich den verzögerten Verlassensbefehl für die erste
Mitgliedschaft ab, während die zweite Lobby aktiv blieb. Der Menübutton
und der Gast-Ausstieg vor dem Handshake sind automatisiert abgedeckt.
