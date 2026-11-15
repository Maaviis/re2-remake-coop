# Experimentelle Lobby-Ansicht

Dieser Entwurf ergänzt die Bridge aus #43 um eine ImGui-Ansicht mit
Host-Auswahl, Einstellungen, Bereitschaft und Einladungsanforderung.
Der native Einzelinstanz-Test am 15. November 2026 bestätigt jetzt die
sichtbare Ansicht und ihre grundlegende Bedienung am Titelbild in
1920x1080. Der Katalogeintrag wurde im Dropdown ausgewählt und vom Host
übernommen; der Einladungsbutton öffnete den echten Steam-Dialog.
Skalierung und Gastbedienung bleiben offen.

## Multiplayer im RE2-Hauptmenü

Auf dem geprüften RE2-Stand ergänzt der Adapter die sechs vorhandenen
Aktionen um **Multiplayer**. Der Eintrag verwendet die native
Hauptmenüliste. Die Auswahl öffnet die Koop-Ansicht. Solange die
Steam-Bridge startet, zeigt sie „Steam-Bridge wartet“. **Zurück**
schließt die Ansicht und gibt die Spieleingabe frei, sobald gehaltene
Eingaben neutral sind.

Der Adapter prüft TDB 70 und die sechs bekannten Hauptmenüaktionen.
Bei abweichender Listenstruktur kann die Diagnoseansicht über F9
verwendet werden, sobald ein Bridge-Status vorhanden ist.

In einer isolierten RE2-Instanz (Steam Build 11636119, REFramework
d1461375) meldete die native Liste sieben Einträge. Das siebte
Menüobjekt meldete „Multiplayer“, Sichtbarkeit und Auswahlindex 6.
Die Auswahl wurde per Terminal auf den nativen Index gesetzt. Lua-Tests
prüfen die Übergabe an die Lobby, die Standardaktionen und den Rückweg.
Die Bestätigung mit regulärer Tastatur-, Maus- und Controller-Eingabe
steht aus.

## Vorbereitung und Terminalbefehle

`reframework/autorun/re2_coop_lobby.lua` und den Unterordner
`reframework/autorun/re2_coop/` in den `autorun`-Ordner der Testinstallation
kopieren. Der Unterordner enthält die benötigte Eingabesteuerung.
Das native Steam-Plugin nach
[dessen Anleitung](network/steam_lobby_probe/README.md) installieren und
die Bridge mit `--lobby` nach [LOBBY_TEST.md](LOBBY_TEST.md) starten.
Die private Steam-Lobby wird weiterhin über `lobby.ps1 create` erstellt.
Nach Auswahl von **Multiplayer** kann die Ansicht auf Bridge-Daten warten.

Die Ansicht benötigt in RE2/TDB 70 kein geöffnetes REFramework-Debug-Menü
mehr. `F9` blendet die Lobby aus und wieder ein. Beim Schließen werden
gehaltene Tasten, Maustasten und Controller-Eingaben zunächst weiterhin
abgefangen, bis die geprüften Eingabequellen zwei Updates lang neutral
sind. [LOBBY_INPUT.md](LOBBY_INPUT.md) beschreibt den nativen Pfad und
den noch begrenzten Spielnachweis.

~~~powershell
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" show
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" hide
python lobby_control.py --data "PFAD-ZU-RE2/reframework/data" invite
~~~

`invite` ist nur für den Host verfügbar. Die Bridge leitet die Anforderung
an die separate native Lobby-Pipe weiter. Die Antwort bestätigt den
Eingang; das Plugin prüft danach Eigentümerschaft und Steam-Overlay.
Erst im Steam-Dialog wird ein Kontakt ausgewählt. Die Anforderung allein
versendet keine Einladung.

## Verhalten der Ansicht

Der Fensterentwurf verwendet dunkle Flächen, helle Schrift und links
ausgerichtete Zeilen als Annäherung an das RE2-Menü. Er liest den lokalen
Host- beziehungsweise Gaststatus. Er verändert keinen autoritativen
Zustand direkt. Auswahl und Bereitschaft gehen als frische Anweisung mit
Sitzung und Revision an dieselbe Bridge wie bei der Terminalbedienung.
Der Gast kann seine eigene Bereitschaft melden. Der Host kann zusätzlich
Auswahl und Einstellungen ändern und den Einladungsdialog anfordern.

Mit `--save-catalog` verwendet die Spielstandzeile den
[nativen Katalog](SAVE_CATALOG.md). Kampagne und gespeicherte
Schwierigkeitsbeschreibung kommen dann aus der bestätigten Auswahl.
Ohne diesen Modus bleibt die bisherige freie Metadaten-Eingabe verfügbar.
Die Engine-Anbindung für Laden und Kampagnenstart fehlt weiterhin.
Die Anzeige ist noch keine spielbare Koop-Lobby.

Bei mehr als drei Sekunden alten Bridge-Daten werden die Bereitschaft
und Eingaben gesperrt. Eine neue Revision setzt den lokalen
Auswahlentwurf auf den neuen Host-Stand zurück. Fehlende optionale
JSON-Dateien werden vor dem Laden über `fs.glob` geprüft.

## Frühere Prüfungen

- 86 Python-Tests bestanden. Der Bridge-Test prüft die
  Einladungsweiterleitung des Hosts und die Ablehnung beim Gast.
- Der Lua-Test prüft Host-Auswahl, Sitzungs-/Revisionsbindung,
  ausstehende Annahme durch den Host, fehlenden Peer, Gastrechte,
  veraltete beziehungsweise defekte Statusdaten und ausgeglichene
  ImGui-Stacks. Er verwendet nachgebildete ImGui-Aufrufe.
- RE2 Build 11636119 und REFramework d1461375: Der Render-Callback
  meldete Host-Daten, Revision und 1920x1080. Der neue Terminal-Controller
  erreichte die native Einladungsanforderung. Es wurde kein Kontakt
  ausgewählt und keine Einladung versendet.
- Die Fensteraufnahmen zeigten keine Lobby-Ansicht. Das blieb auch nach
  vorübergehender Isolation der bestehenden Autorun- und Plugin-Ordner
  so. Der Grund ist ungeklärt; ein Fremdmod-Konflikt ist nicht belegt.
- Beide Spieltests liefen ohne Laden eines Kampagnenspielstands.
  Danach wurden RE2 und die Bridge beendet und die Originalordner sowie
  gesicherte Diagnosedateien wiederhergestellt. Alle zwölf zuvor erfassten
  Steam-Spielstanddateien blieben bytegleich; es kamen keine hinzu.

Die folgenden Render-Vergleiche erklären, weshalb diese früheren
Fensteraufnahmen noch keinen sichtbaren Nachweis lieferten. Der spätere
aktive Bildschirmtest ist im letzten Abschnitt festgehalten.

API-Grundlage: [REFramework ImGui](https://cursey.github.io/reframework-book/api/imgui.html),
[Frame-Callbacks](https://cursey.github.io/reframework-book/api/re.html),
[Dateizugriff](https://cursey.github.io/reframework-book/api/fs.html).

## Renderdiagnose am 14./15. November 2026

Die Stilfarben werden jetzt als vorzeichenbehaftete 32-Bit-Werte an
`imgui.push_style_color` übergeben. Der
[geprüfte Binding-Stand](https://github.com/praydog/REFramework/blob/d1461375aee4ec3f313170f8eaad12064eb542d9/src/mods/bindings/ImGui.cpp#L1198)
prüft dort `sol::object::is<int>()`. Der Lua-Test bildet diese Grenze
ab: Die vorherige Fassung scheitert, die korrigierte besteht. Das ist
keine Bestätigung, dass der sichtbare Renderfehler damit behoben ist.

Für einen isolierten Vergleich enthält
`reframework/diagnostics/re2_coop_render_probe.lua` eine unabhängige Probe:
ein farbiges Rechteck, Text und ein einfaches ImGui-Fenster ohne eigene
Schrift oder Stilfarben. Sie verändert keinen Spielzustand. RE2 beenden,
die Datei für den Test in `reframework/autorun` kopieren und danach wieder
entfernen. `RE2_COOP_RENDER_PROBE` meldet Anzeigegröße, Fensterposition,
Fenstermaß und den Menüstatus im REFramework-Log.

In den nativen Vergleichsläufen mit d1461375 und der offiziellen Nightly
f00d6bee lief diese Probe bei 1920x1080 und meldete das erwartete Fenster
bei 950,240 mit 500x180. Die Aufnahmen zeigten auch diese Minimalanzeige
nicht. Ein abgegrenzter Nightly-Lauf protokollierte 7.974
ImGui-Neuinitialisierungen und 16.079 Resize-Buffer-Aufrufe des D3D12-Pfads.
Damit war die Störung nicht auf das Lobby-Layout eingegrenzt. Die Ursache
der wiederholten Resets ist weiterhin ungeklärt; im späteren aktiven
Vollbildtest trat dieser fortlaufende Reset-Zustand nicht auf.

Das Setzen von `TargetPlatform` und `PCDXver` auf `DirectX11` änderte in
dieser Installation den tatsächlich protokollierten D3D12-Backendpfad
nicht. Deshalb zählt dieser Versuch nicht als DX11-Nachweis und begründet
keine Empfehlung zum Umstellen des Renderers.

Die originale Dinput8-Verknüpfung, Mod-Ordner, Grafik- und Diagnosedateien
wurden nach dem Vergleich wiederhergestellt. Die DLL und gesicherten
Grafik-/Diagnosedateien wurden über Prüfsummen geprüft.
RE2 und Bridge sind beendet. Es wurde keine Kampagne geladen; alle zwölf
erfassten Dateien im Steam-Spielstandordner blieben bytegleich und es
kamen keine hinzu. Die Nightly-Version wurde nicht dauerhaft installiert.

## Sichtbare native Prüfung am 15. November 2026

Mit der ursprünglichen Dinput8-Verknüpfung (d1461375), unveränderten
Grafikwerten und aktivem RE2-Vollbild lieferte die Bildschirmaufnahme
sichtbare Ergebnisse. Die isolierte Minimalprobe zeichnete Rechteck,
Text und Fenster. Im anschließenden Lauf mit Lobby, Save-Katalog und
Steam-Plugin erschienen auch die vollständige Host-Ansicht und ihr
Dropdown. Beide Läufe hatten jeweils zwei ImGui-Initialisierungen und
fünf Resize-Buffer-Aufrufe statt einer fortlaufenden Reset-Schleife.
Die Ursache des früheren Verhaltens ist damit nicht bewiesen.

Die Bildprüfung verwendete den sichtbaren Bildschirmbereich des
Vordergrundfensters. `PrintWindow`-Aufnahmen allein hatten die
Darstellung zuvor nicht bestätigt. Eine Fensterabfrage aus einem
isolierten Terminal lieferte Handle 0; der freigegebene Aufruf auf dem
interaktiven Desktop bestätigte dagegen das aktive RE2-Fenster.
Eine Abfrage ohne gültiges Spielfenster zählt nicht als Renderprüfung.

Der wiederverwendbare Helfer ändert weder Fokus noch Fenstergröße oder
Grafikmodus. Er prüft den RE2-Vordergrundprozess vor und nach der Aufnahme,
verwendet Bildschirmkoordinaten mit DPI-Abgleich und speichert lokal:

~~~powershell
./scripts/capture_re2_frame.ps1 -OutputPath ./staging/re2-frame.png
~~~

Der Ausgabeordner muss bestehen. Bei mehreren Instanzen ist
`-GameProcessId` anzugeben. Der Aufruf benötigt Zugriff auf den
interaktiven Desktop, auf dem RE2 bereits im Vordergrund steht.
Aufnahmen des Steam-Dialogs bleiben lokal; der Test veröffentlicht keine
Freundesliste oder persönlichen Spielstanddaten.

Die reale Mausbedienung erfolgte über das Terminal und wurde vor jedem
Klick an den RE2-Vordergrundprozess gebunden. Der Datumsfilter bot nur
Slot 4 vom 11.11.2026 an. Nach Auswahl und Übernehmen zeigte die Bridge
`scenario:4`, die bestätigte Kampagne und eine höhere Lobby-Revision.
Der Bereit-Knopf blieb ohne Gast gesperrt und erzeugte keine Anweisung.
Der Einladungsbutton öffnete den echten Steam-Einladungsdialog. Er wurde
ohne Kontaktwahl geschlossen. `hide`/`show` blendeten die Ansicht aus
und ein. Nach Ende der Bridge erzeugte auch ein Klick auf die veraltete
Ansicht keine neue Konfigurationsanweisung.

REFrameworks Menü war für diesen ersten Bediennachweis geöffnet und dessen
Eingabedurchleitung ausgeschaltet. Die endgültige eigenständige
Eingabesteuerung und die Trennung vom Debug-Menü sind noch zu entwickeln;
die UI darf später keine Interaktion an das laufende Spiel durchreichen.
Der anschließende Entwurf aus [LOBBY_INPUT.md](LOBBY_INPUT.md) ersetzt
diese Abhängigkeit und bestätigt den eigenen Eingabepfad am Titelbild.
Weitere Auflösungen, Tastatur-/Controllerbedienung und die Gastansicht
mit einer zweiten echten Spielinstanz sind noch nicht abgenommen.

Danach wurden die private Lobby verlassen, die Bridge und RE2 beendet
und Originalordner, Konfiguration und Diagnosedateien wiederhergestellt.
Alle zwölf erfassten Steam-Spielstanddateien blieben bytegleich; es kamen
keine hinzu. Eine Kampagne wurde nicht geladen.
