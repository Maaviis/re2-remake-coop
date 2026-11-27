# Nativer Spielstandkatalog für die Lobby

Der Host kann die Lobby-Auswahl jetzt an die vorhandene Szenario-Tabelle
des Spiels binden. `re2_coop_save_catalog.lua` liest ausschließlich die
Metadaten aus `app.ropeway.gamemastering.SaveDataManager`. Es ruft keine
Speicher-, Lade-, Lösch- oder Setter-Funktion auf.

## Start und Bedienung

Bei beendetem RE2 `reframework/autorun/re2_coop_save_catalog.lua` in den
`autorun`-Ordner der Testinstallation kopieren. Dieselbe Bridge-Fassung
auf beiden Rechnern verwenden. Die Steam-Lobby nach
[STEAM_POSE_TEST.md](../lobby/STEAM_POSE_TEST.md) erstellen und betreten.

Der Host aktiviert den nativen Katalog mit `--save-catalog`. Der optionale
Datumsfilter begrenzt die auswählbaren Einträge. Für den hier freigegebenen
Testbestand lautet er `2026-11-11`:

~~~powershell
$re2Pid = (Get-Process -Name re2).Id
python bridge/steam_pose_bridge.py --role host --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby --save-catalog --allow-save-date 2026-11-11
# In einem zweiten Terminal:
python bridge/lobby_control.py --data "PFAD-ZU-RE2/reframework/data" saves
python bridge/lobby_control.py --data "PFAD-ZU-RE2/reframework/data" select scenario:4
python bridge/lobby_control.py --data "PFAD-ZU-RE2/reframework/data" status
~~~

`scenario:4` ist eine vom nativen Katalog bestätigte Slotkennung dieses
Testbestands. Andere Installationen wählen einen ihrer tatsächlich
aufgelisteten Schlüssel. Die Eingabe bezeichnet keinen Dateipfad.
Der Gast erhält die Auswahl des Hosts. Für die Bereitschaft in einer
nativen Lobby startet er die Bridge ebenfalls mit dem eigenen Katalog
und dem für seinen Testbestand freigegebenen Datum.

~~~powershell
python bridge/steam_pose_bridge.py --role guest --pid $re2Pid --data "PFAD-ZU-RE2/reframework/data" --lobby --save-catalog --allow-save-date 2026-11-11
~~~

`lobby_control.py status` zeigt beim Gast in `local_save_matches`, ob
Modus, Slot, nativer Zeitwert und Szenario lokal zur Host-Auswahl passen.
Anzeigetexte dürfen sich unterscheiden. Fehlt der passende Eintrag oder
verliert der Gastkatalog seine Gültigkeit, nimmt die Gast-Bridge ihre
Bereitschaft zurück. Sobald der Eintrag wieder verfügbar ist, kann der
Gast seine Bereitschaft erneut melden. Der Abgleich erfasst Metadaten.

Im Menüentwurf aus [LOBBY_MENU.md](../lobby/LOBBY_MENU.md) ersetzt dieser Modus die
freie Slot-Eingabe durch die Katalogauswahl. Kampagne und die erste
Beschreibungszeile des Spielstands werden angezeigt. Diese Werte gehören
zur Speicherung und werden nicht durch frei gewählte Lobby-Einstellungen
ersetzt. Die sichtbare Host-Auswahl wurde am Titelbild in 1920x1080 nativ
bedient; weitere Auflösungen und die Gastansicht bleiben ungeprüft.

## Zustandsabgleich

Der native Export enthält bis zu 21 Szenario-Plätze einschließlich
Autospeicherplatz 0. Leere Referenzen und als leer gemeldete Daten werden
ausgelassen. Der Exporter prüft vorher und nachher, ob der Save-Service
beschäftigt ist. Währenddessen oder bei nicht zugänglicher Tabelle
veröffentlicht er einen nicht verfügbaren Katalog.

Die Bridge prüft Schema, RE2/TDB 70, Szenariotyp, Slotgrenzen,
Zeitdarstellung, Sequenz und Frische. Ein angebrochener JSON-Schreibvorgang
erneuert die bisherige Drei-Sekunden-Frist nicht. Eine gültige Meldung
über einen beschäftigten Save-Service sperrt die Auswahl sofort.

Eine angenommene Auswahl erhält `save_ref` in der Host-Lobby. Sie enthält
Modus, Slot, nativen Zeitwert, Szenariotyp, Beschriftung und einen Digest
der gelesenen Metadaten. Wenn sich diese Referenz ändert oder ihre Quelle
ausfällt, erhöht der Host die Lobby-Revision und setzt beide
Bereitschaftswerte zurück. Alte Bereitschaftsmeldungen können danach
keinen Startzustand herstellen. Auch direkt geschriebene lokale
Auswahlanweisungen müssen den Katalog und Datumsfilter des Hosts passieren.

Der Digest umfasst die Metadaten, nicht die verschlüsselte Speicherdatei.
Es besteht noch kein Integritätsnachweis für den vollständigen
Spielstandinhalt. Der native Zeitwert wird als Dezimalstring übertragen,
damit er nicht an einer JSON-/Lua-Zahlengrenze gerundet wird. Die
Kalenderumrechnung entspricht DateTime-Ticks und passte beim gemessenen
Slot zum Datum des Spielstands. Eine Zeitzonenart liefert der verwendete
Getter nicht mit; der Datumsfilter gilt für diese Engine-Kalenderdarstellung.

## Geprüfter Stand und offene Arbeiten

Der native Einzelinstanz-Test am 15. November 2026 verwendete RE2
Steam-Build 11636119, REFramework d1461375 und TDB 70. Der Save-Manager
und die Szenario-Tabelle waren bereits am Titelbild zugänglich. Es gab
neun vorhandene Metadaten-Einträge. Der Datumsfilter ließ genau Slot 4
vom 11.11.2026 zu. Die Host-Bridge übernahm ihn und wies eine direkt
eingeschleuste neuere Auswahl ab. Bereitschaft ohne Gast blieb gesperrt.

In einer weiteren nativen Prüfung wurde derselbe erlaubte Eintrag im
sichtbaren ImGui-Dropdown per terminalgesteuerter Maus ausgewählt und
übernommen. Der Host bestätigte `scenario:4`, Kampagne und eine höhere
Revision. Der Bereit-Knopf erzeugte ohne Gast keine Anweisung. Der
Einladungsbutton öffnete den echten Steam-Dialog; es wurde kein Kontakt
ausgewählt. [LOBBY_MENU.md](../lobby/LOBBY_MENU.md) beschreibt die Bedingungen,
Bildprüfung und verbleibende Eingabesteuerung.

RE2 wurde danach geschlossen. Die ursprünglichen Mod-Ordner,
Grafikwerte und Diagnosedateien wurden zurückgestellt. Alle zwölf
vor dem Test erfassten Dateien im Steam-Spielstandordner hatten danach
dieselben SHA-256-Prüfsummen; es kamen keine hinzu. Eine Kampagne wurde
nicht geladen.

Python- und Lua-Regressionen sowie ein Test mit zwei Bridge-Schleifen
prüfen die Metadatenkette, Datumsfilter, Null-Einträge, Lua-JSON-Übergabe,
abgelaufene Quellen, falsche Referenzen und das Zurücksetzen der
Bereitschaft nach Änderung. Der Nachrichtenlink ist dabei simuliert.

Laden des ausgewählten RE2-Spielstands, gemeinsames Speichern, Abgleich
des vollständigen Spielzustands und der Nachweis mit zwei echten
Spielinstanzen bleiben offen. Für diesen Test steht bisher kein zweiter
PC mit eigenem Steam-Konto zur Verfügung. Die Auswahl allein startet
keine Kampagne und ist keine Freigabe einer spielbaren Koop-Mod.
