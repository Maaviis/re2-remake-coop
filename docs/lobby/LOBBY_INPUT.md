# Eigenständige Eingabe für die Lobby

Die Lobby aus #45 lässt sich mit diesem Entwurf ohne geöffnetes
REFramework-Debug-Menü bedienen. `F9` schließt und öffnet die Ansicht;
die Terminalbefehle `show` und `hide` bleiben verfügbar. Auswahl und
Bereitschaft laufen weiterhin durch dieselbe Host-Bridge.
Ein beim Spielstart bereits abgelaufenes Statusdokument aus einem
früheren Lauf öffnet keine modale Ansicht. Erst frische Bridge-Daten
aktivieren sie. Ein späterer Verbindungsabbruch sperrt wie bisher die
Steuerelemente der bereits geöffneten Lobby; F9 bleibt verfügbar.

## Installation und Verhalten

In der Multiplayer-Ansicht wechseln Pfeil hoch und runter zwischen den
verfügbaren Aktionen. Links und rechts wechseln den ausgewählten Slot,
Eingabe oder Leertaste aktiviert die markierte Schaltfläche. Esc führt
zurück. Während der Bearbeitung eines Felds oder in einem geöffneten
Dropdown bleibt die Eingabe beim Feld. Nach einer Renderunterbrechung
und beim Öffnen der Ansicht müssen die Navigationstasten zuerst losgelassen
werden. Die Tastaturbedienung ist mit der Lua-Laufzeit geprüft (E2).

Zusätzlich zu `re2_coop_lobby.lua` muss der Unterordner
`reframework/autorun/re2_coop/` einschließlich `lobby_input.lua` in der
Testinstallation liegen. Der Lua-Modulpfad des geprüften REFramework-
Stands lädt diesen Unterordner über `require`; er wird nicht als eigenes
Autorun-Skript ausgeführt. Steam-Plugin, Bridge und Katalog werden wie in
[LOBBY_MENU.md](LOBBY_MENU.md) und [SAVE_CATALOG.md](../campaign/SAVE_CATALOG.md) eingerichtet.

Die Eingabesteuerung unterstützt zunächst RE2 mit TDB 70. Sie hängt sich
nach `app.ropeway.InputSystem.update` ein und ruft bei sichtbarer Lobby
`setInhibit(System.Boolean)` mit `true` auf. Der native Test bestätigte,
dass der originale Update-Pfad die Maske pro Frame zurücksetzt. Der Mod
ruft nie `setInhibit(false)` auf und verändert weder `Reset` noch
`SkipReset` oder die Maske anderer Anforderungen direkt.

Für Cursor und Kameramauseingabe registriert der Mod die eigenen
Anforderungen `requestShowMouseCursor` und `requestIgnoreMouseMove` mit
dem Schlüssel `re2_coop_lobby`. Beim Freigeben oder Skript-Reset entfernt
er nur die Anträge dieses Schlüssels. Eine fehlgeschlagene Teilanforderung
wird ebenfalls zurückgenommen. Fehlen die benötigten Schnittstellen,
bleibt die bedienbare Ansicht ausgeblendet.

Die sichtbare Ansicht erneuert eine kurze Frist. Bleibt ihr Render-Aufruf
aus, fordert die Steuerung bei weiterlaufenden Input-Updates nach
spätestens zwei Sekunden die Freigabe an. Beim Schließen wird zunächst
weiter gesperrt, solange eine gelesene
Eingabequelle noch aktiv ist. Erst zwei neutrale Input-Updates beenden
die Sperre. Dies verhindert, dass der noch gehaltene Schließklick oder
eine gehaltene Taste unmittelbar am Spiel ankommt.

Für diesen Übergang werden die unabhängigen REFramework-Tastenereignisse
und ImGui-Maustasten sowie die nativen Tastatur-, Maus- und zugeordneten
Gamepadwerte gelesen. Controllerachsen haben einen Neutralbereich von
0,25; analoge Trigger gelten bis 0,1 als neutral. Der native Halte-Test
zeigte, dass die Engine-Gerätewerte allein die noch gehaltene Maustaste
nicht zuverlässig abbildeten. Daher sind die unabhängigen Fensterwerte
Teil der Freigabebedingung. Der Regressionstest schlägt ohne diese
Ergänzung fehl.

`re2_coop_lobby_input.json` enthält lokal Schema, Zeit, gewünschten und
zuletzt gesetzten Erfassungszustand, Grund sowie den Debug-Menüstatus. Es
enthält keine Tastencodes oder Eingabehistorie. Die Datei dient der
Diagnose und ist keine Netzwerk- oder Kampagnenautorität.

## Nativer Nachweis am 15. November 2026

Die Tests verwendeten RE2 Steam-Build 11636119, REFramework d1461375,
TDB 70 und die ursprünglichen D3D12-Grafikwerte in 1920x1080. Alle
Spielaktionen erfolgten über Terminalhelfer, die vor jedem Eingriff den
RE2-Vordergrundprozess prüften. Das Debug-Menü war geschlossen.

- Die vollständige Host-Lobby war sichtbar. Der Katalogeintrag vom
  11.11.2026 wurde im Dropdown ausgewählt und übernommen; die Bridge
  bestätigte `scenario:4`, Kampagne und eine höhere Revision.
- F9 blendete die Ansicht aus und ein. Bei gehaltener linker Maustaste
  blieb nach F9 `wanted=false`, `captured=true` und
  `reason=release_held_input`. Erst nach Mouse-up folgte `inactive`.
  Derselbe Vergleich bestand mit einer gehaltenen W-Taste.
- Ein gehaltener Klick auf den sichtbaren Titelbildknopf unter der
  geöffneten Lobby änderte den Menüschritt nicht. Nach F9 und Freigabe
  öffnete derselbe Klick das originale Hauptmenü. Es wurde keine
  Kampagne ausgewählt oder geladen.
- Danach wurden die private Steam-Lobby verlassen, Bridge und RE2
  beendet und Originalordner, Konfiguration und Diagnosedateien
  zurückgestellt. Alle zwölf erfassten Steam-Spielstanddateien hatten
  dieselben SHA-256-Werte; es kamen keine hinzu.

Die Lua-Prüfungen ergänzen diesen begrenzten nativen Nachweis um
gehaltene Controllerbuttons, Zusatzbuttons, Achsen und Trigger,
ausbleibende Render-Aufrufe, fehlende Singletons, Teilfehler und
Skript-Reset. Diese Controllerfälle sind nachgebildet; eine Prüfung
mit physischem Controller ist noch offen.

## Verbleibende Prüfungen

Ein weiterer Einzelinstanz-Test lud über das Originalmenü ausschließlich
den freigegebenen alten Spielstand. Bei sichtbarer Lobby und geschlossenem
Debug-Menü ergab eine 200 ms gehaltene S-Taste über 37 frische
Observer-Proben keine Positionsänderung. Nach F9 und Freigabe veränderte
dieselbe Eingabe über 22 frische Proben die Position um rund 0,073 m.
Alle zwölf erfassten Speicherdateien blieben unverändert. Das belegt
diesen Bewegungsvergleich in einem sicheren Kampagnenraum.

Zielen, Schießen und Zwischensequenzen sind noch nicht abgenommen.
Ebenso fehlen physische
Controller-, Fokuswechsel-, Auflösungs- und Zwei-Instanzen-Tests. Die
damals geprüfte Lobby konnte noch keinen nativen Kampagnenstart anfordern.
Die gesonderte Entwickler-Ladeprobe und ihr offener Menüabschluss sind
in [READONLY_LOAD.md](../campaign/READONLY_LOAD.md) dokumentiert.

API-Grundlagen: [geprüfte Hook- und Modulbindung](https://github.com/praydog/REFramework/blob/d1461375aee4ec3f313170f8eaad12064eb542d9/src/mods/ScriptRunner.cpp),
[Fenster- und Tastaturereignisse](https://github.com/praydog/REFramework/blob/d1461375aee4ec3f313170f8eaad12064eb542d9/src/REFramework.cpp)
und die im RE2-Laufzeittyp bestätigten InputSystem-Methoden. Die
Implementierung verwendet keine angenommenen Speicheradressen.
