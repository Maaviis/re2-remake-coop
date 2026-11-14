# Experimentelle Lobby-Ansicht

Dieser Entwurf ergänzt die Bridge aus #43 um eine ImGui-Ansicht mit
Host-Auswahl, Einstellungen, Bereitschaft und Einladungsanforderung.
Der visuelle Nachweis im Spiel ist noch offen: Die Lua-Renderfunktion
läuft nativ, aber die geprüften Fensteraufnahmen zeigen die Ansicht
nicht. Deshalb ist diese Fassung noch keine abgenommene Menüintegration.

## Vorbereitung und Terminalbefehle

`reframework/autorun/re2_coop_lobby.lua` in den `autorun`-Ordner der
Testinstallation kopieren. Das native Steam-Plugin nach
[dessen Anleitung](network/steam_lobby_probe/README.md) installieren und
die Bridge mit `--lobby` nach [LOBBY_TEST.md](LOBBY_TEST.md) starten.
Die private Steam-Lobby wird weiterhin über `lobby.ps1 create` erstellt.
Ohne Bridge-Daten zeichnet das Skript keine Ansicht.

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

Die Spielstandzeile enthält bisher eine Slotkennung. Es gibt noch keinen
Katalog echter RE2-Spielstände und keine Engine-Anbindung für Laden oder
Kampagnenstart. Die Dropdowns übertragen nur Kampagnen- und
Schwierigkeitsmetadaten. Die Anzeige darf daher noch nicht als spielbare
Koop-Lobby behandelt werden.

Bei mehr als drei Sekunden alten Bridge-Daten werden die Bereitschaft
und Eingaben gesperrt. Eine neue Revision setzt den lokalen
Auswahlentwurf auf den neuen Host-Stand zurück. Fehlende optionale
JSON-Dateien werden vor dem Laden über `fs.glob` geprüft.

## Geprüfter Stand

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

Als Nächstes die tatsächliche Ausgabe der ImGui-Fenster im RE2-Renderpfad
prüfen. Danach Layout, Skalierung, Bedienung und Steam-Dialog in einer
sichtbaren Einzelinstanz abnehmen und schließlich Host/Gast mit zwei
echten Spielinstanzen vergleichen.

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
Damit ist die Störung nicht auf das Lobby-Layout eingegrenzt. Ihre Ursache
ist weiterhin ungeklärt. Ein aktiver Bildnachweis des stabilen
Ausgabepfads steht aus.

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
