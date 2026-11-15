# Eigenst�ndige Eingabe f�r die Lobby

Die Lobby aus #45 l�sst sich mit diesem Entwurf ohne ge�ffnetes
REFramework-Debug-Men� bedienen. `F9` schlie�t und �ffnet die Ansicht;
die Terminalbefehle `show` und `hide` bleiben verf�gbar. Auswahl und
Bereitschaft laufen weiterhin durch dieselbe Host-Bridge.
Ein beim Spielstart bereits abgelaufenes Statusdokument aus einem
fr�heren Lauf �ffnet keine modale Ansicht. Erst frische Bridge-Daten
aktivieren sie. Ein sp�terer Verbindungsabbruch sperrt wie bisher die
Steuerelemente der bereits ge�ffneten Lobby; F9 bleibt verf�gbar.

## Installation und Verhalten

Zus�tzlich zu `re2_coop_lobby.lua` muss der Unterordner
`reframework/autorun/re2_coop/` einschlie�lich `lobby_input.lua` in der
Testinstallation liegen. Der Lua-Modulpfad des gepr�ften REFramework-
Stands l�dt diesen Unterordner �ber `require`; er wird nicht als eigenes
Autorun-Skript ausgef�hrt. Steam-Plugin, Bridge und Katalog werden wie in
[LOBBY_MENU.md](LOBBY_MENU.md) und [SAVE_CATALOG.md](SAVE_CATALOG.md) eingerichtet.

Die Eingabesteuerung unterst�tzt zun�chst RE2 mit TDB 70. Sie h�ngt sich
nach `app.ropeway.InputSystem.update` ein und ruft bei sichtbarer Lobby
`setInhibit(System.Boolean)` mit `true` auf. Der native Test best�tigte,
dass der originale Update-Pfad die Maske pro Frame zur�cksetzt. Der Mod
ruft nie `setInhibit(false)` auf und ver�ndert weder `Reset` noch
`SkipReset` oder die Maske anderer Anforderungen direkt.

F�r Cursor und Kameramauseingabe registriert der Mod die eigenen
Anforderungen `requestShowMouseCursor` und `requestIgnoreMouseMove` mit
dem Schl�ssel `re2_coop_lobby`. Beim Freigeben oder Skript-Reset entfernt
er nur die Antr�ge dieses Schl�ssels. Eine fehlgeschlagene Teilanforderung
wird ebenfalls zur�ckgenommen. Fehlen die ben�tigten Schnittstellen,
bleibt die bedienbare Ansicht ausgeblendet.

Die sichtbare Ansicht erneuert eine kurze Frist. Bleibt ihr Render-Aufruf
aus, fordert die Steuerung bei weiterlaufenden Input-Updates nach
sp�testens zwei Sekunden die Freigabe an. Beim Schlie�en wird zun�chst
weiter gesperrt, solange eine gelesene
Eingabequelle noch aktiv ist. Erst zwei neutrale Input-Updates beenden
die Sperre. Dies verhindert, dass der noch gehaltene Schlie�klick oder
eine gehaltene Taste unmittelbar am Spiel ankommt.

F�r diesen �bergang werden die unabh�ngigen REFramework-Tastenereignisse
und ImGui-Maustasten sowie die nativen Tastatur-, Maus- und zugeordneten
Gamepadwerte gelesen. Controllerachsen haben einen Neutralbereich von
0,25; analoge Trigger gelten bis 0,1 als neutral. Der native Halte-Test
zeigte, dass die Engine-Ger�tewerte allein die noch gehaltene Maustaste
nicht zuverl�ssig abbildeten. Daher sind die unabh�ngigen Fensterwerte
Teil der Freigabebedingung. Der Regressionstest schl�gt ohne diese
Erg�nzung fehl.

`re2_coop_lobby_input.json` enth�lt lokal Schema, Zeit, gew�nschten und
zuletzt gesetzten Erfassungszustand, Grund sowie den Debug-Men�status. Es
enth�lt keine Tastencodes oder Eingabehistorie. Die Datei dient der
Diagnose und ist keine Netzwerk- oder Kampagnenautorit�t.

## Nativer Nachweis am 15. November 2026

Die Tests verwendeten RE2 Steam-Build 11636119, REFramework d1461375,
TDB 70 und die urspr�nglichen D3D12-Grafikwerte in 1920x1080. Alle
Spielaktionen erfolgten �ber Terminalhelfer, die vor jedem Eingriff den
RE2-Vordergrundprozess pr�ften. Das Debug-Men� war geschlossen.

- Die vollst�ndige Host-Lobby war sichtbar. Der Katalogeintrag vom
  11.11.2026 wurde im Dropdown ausgew�hlt und �bernommen; die Bridge
  best�tigte `scenario:4`, Kampagne und eine h�here Revision.
- F9 blendete die Ansicht aus und ein. Bei gehaltener linker Maustaste
  blieb nach F9 `wanted=false`, `captured=true` und
  `reason=release_held_input`. Erst nach Mouse-up folgte `inactive`.
  Derselbe Vergleich bestand mit einer gehaltenen W-Taste.
- Ein gehaltener Klick auf den sichtbaren Titelbildknopf unter der
  ge�ffneten Lobby �nderte den Men�schritt nicht. Nach F9 und Freigabe
  �ffnete derselbe Klick das originale Hauptmen�. Es wurde keine
  Kampagne ausgew�hlt oder geladen.
- Danach wurden die private Steam-Lobby verlassen, Bridge und RE2
  beendet und Originalordner, Konfiguration und Diagnosedateien
  zur�ckgestellt. Alle zw�lf erfassten Steam-Spielstanddateien hatten
  dieselben SHA-256-Werte; es kamen keine hinzu.

Die Lua-Pr�fungen erg�nzen diesen begrenzten nativen Nachweis um
gehaltene Controllerbuttons, Zusatzbuttons, Achsen und Trigger,
ausbleibende Render-Aufrufe, fehlende Singletons, Teilfehler und
Skript-Reset. Diese Controllerf�lle sind nachgebildet; eine Pr�fung
mit physischem Controller ist noch offen.

## Verbleibende Pr�fungen

Ein weiterer Einzelinstanz-Test lud �ber das Originalmen� ausschlie�lich
den freigegebenen alten Spielstand. Bei sichtbarer Lobby und geschlossenem
Debug-Men� ergab eine 200 ms gehaltene S-Taste �ber 37 frische
Observer-Proben keine Positions�nderung. Nach F9 und Freigabe ver�nderte
dieselbe Eingabe �ber 22 frische Proben die Position um rund 0,073 m.
Alle zw�lf erfassten Speicherdateien blieben unver�ndert. Das belegt
diesen Bewegungsvergleich in einem sicheren Kampagnenraum.

Zielen, Schie�en und Zwischensequenzen sind noch nicht abgenommen.
Ebenso fehlen physische
Controller-, Fokuswechsel-, Aufl�sungs- und Zwei-Instanzen-Tests. Die
Lobby steuert weiterhin weder RE2-Laden noch einen Kampagnenstart.
Die gesonderte Entwickler-Ladeprobe und ihr offener Men�abschluss sind
in [READONLY_LOAD.md](READONLY_LOAD.md) dokumentiert.

API-Grundlagen: [gepr�fte Hook- und Modulbindung](https://github.com/praydog/REFramework/blob/d1461375aee4ec3f313170f8eaad12064eb542d9/src/mods/ScriptRunner.cpp),
[Fenster- und Tastaturereignisse](https://github.com/praydog/REFramework/blob/d1461375aee4ec3f313170f8eaad12064eb542d9/src/REFramework.cpp)
und die im RE2-Laufzeittyp best�tigten InputSystem-Methoden. Die
Implementierung verwendet keine angenommenen Speicheradressen.
