# Lesender Timeline-Beobachter

Für eine gemeinsame Ladepause und synchronisierte Zwischensequenzen reicht
ein stehender Spielzeitzähler nicht aus. Dieser Entwurf ergänzt deshalb
getrennte native Messwerte für Kameraereignisse, aktive Timeline-Inhalte
und die Filmwiedergabe. Er ist eine Diagnose auf Basis von #104 und gibt
keine gemeinsame Spielfreigabe.

## Umfang

`re2_coop/timeline_state.lua` prüft RE2/TDB 70 und sämtliche verwendeten
Getter-/Feldsignaturen beim Start. Es liest ausschließlich außerhalb von
Hooks. Titelbild, laufender Load, unvollständige Szene, beschäftigter
Save-Manager und fehlende Manager ergeben keine verfügbare Zustandsprobe.
Ein fehlendes Objekt wird nicht als beendetes Ereignis ausgegeben.

| Quelle | Exportierte Werte |
|---|---|
| `TimelineEventManager` | Kameraereignis, Standby, Wiedergabe, Skip-Verfügbarkeit und Skip-Status, Untertitelstatus, rohe Pausenindikatoren |
| Aktive `TimelineContents` | Ereigniskennung, roher Prozess-/Auftragswert, Aktivität, Pause, Standby, Skip-Verfügbarkeit und Film-Frame |
| `TimelinePerformance` je aktivem Inhalt | Roher Ausführungsstatus, Abschlussindikator und aktuelle `PerformanceInfo`, auch ohne aktives Kameraereignis |
| Aktive Kamera-`PerformanceInfo`, wenn vorhanden | Ereigniskennung, Flow-Kennung, roher Ereignisstatus, Kamera-/Skip-Werte |
| Zugehörige `via.timeline.Timeline`, wenn vorhanden | Tatsächlicher Frame, roher Wiedergabestatus, Geschwindigkeit und Gültigkeit |
| `MovieManager` | Boolescher Wiedergabeindikator; keine einzelnen Filmplayer oder deren Zeitverlauf |

Jeder aktive Inhalt wird zusätzlich über `get_Performance()` und
`get_CurrentEventInfo()` gelesen. Damit erreicht der Leser auch die
Timeline-/Flowwerte freier Ereignisse, die nicht in der Kameraquelle des
Managers stehen. Die aktuelle Performance muss dieselbe Ereigniskennung
wie ihr Inhalt haben. Eine fehlende Ausführung oder Ereignisinformation
bleibt ausdrücklich `present=false`; deren Fehlen erzeugt kein Endereignis.

`camera.wwise_frame` ist der separat bezeichnete Audio-Wert aus
`get_CurrentFrameForWwise`. Er wird niemals als Frame der eigentlichen
Timeline ausgegeben. Rohe Enumwerte werden nicht in unbestätigte Phasen wie
„gestartet“ oder „beendet“ übersetzt. Fehlende Performance/Timeline wird
durch `present=false` dargestellt, nicht durch einen erfundenen Frame 0.

Zwei unmittelbar aufeinanderfolgende Abfragen müssen die gleichen Werte
und lokalen Objekte liefern. Wechselnde Manager, Inhalte, Performance oder
Timeline sowie ein Übergang beim Lesen verwerfen die gesamte Probe.
Die Objektadressen dienen nur dem lokalen Vergleich. Daten werden in neue
Lua-Tabellen kopiert. Mehr als 64 aktive Inhalte, doppelte Ereigniskennungen,
falsche Typen, NaN, Unendlich und Getterfehler liefern keine Zustandsprobe.
Änderungen zwischen den Doppelabfragen können daher auch bei legitimer
laufender Wiedergabe zu `state_changed` führen; der Leser erfindet keinen
Ersatzwert.

## Optionaler Export

Die separate Diagnose
`reframework/diagnostics/re2_coop_timeline_state_observer.lua` ist im
normalen Autorun nicht aktiviert. In einer gesondert geschützten
Entwicklungsinstallation veröffentlicht sie alle sechs `UpdateBehavior`-
Aufrufe eine lokale `re2_coop_timeline_state.json` mit:

- `schema=2`, `source=re2`, `tdb=70`, `scope=native_timeline_activity`;
- eigener VM-Laufkennung, steigender Sequenz und Beobachtungszeit;
- `available`, `reason` und nur bei Erfolg einem `state`.

Bei einer ausgefallenen Abfrage wird der alte Zustand nicht erneut als
frischer Erfolg veröffentlicht. Eine leere Lua-Sequenz kann REFramework als
JSON `null` schreiben; nur `active_count=0` beschreibt diese leere Liste.
Ein künftiger Dateileser muss Quelle, Umfang, Sequenz, Frist und die eigene
Lade-/Prozessbindung prüfen. Dieser Entwurf transportiert nichts über
Steam und ändert weder bestehende Netzwerkformate noch das Nutzerpaket.
Unterformat 2 ergänzt `contents[].performance`; ein Leser für Unterformat 1
darf diese Erweiterung nicht stillschweigend als vollständig akzeptieren.

## Prüfung und Grenzen

Die Lua-Suite prüft aktive nachgebildete Kamera-/Timeline-Daten, getrennte
Framequellen, fehlende Performance/Timeline, Titel-/Ladephasen, Grenzen,
Typfehler, Objektaustausch und Änderungen zwischen beiden Abfragen. Der
Exporttest bestätigt Takt, Sequenz und das Entfernen alter Zustandswerte
nach einem Fehler. Auf dem finalen Stand bestehen 233 Python-Tests und
20 Lua-Suiten.

Zusätzliche Fälle prüfen freie Timeline-Frames bei fehlender Kameraquelle,
fehlende Ausführung/Performance/Timeline, eine falsche Ereigniszuordnung und
einen Ausführungs- oder Framewechsel zwischen den beiden Abfragen. Die
verwendeten freien Getter wurden in einer weiteren geschützten nativen
Metadatenprüfung bestätigt. Eine laufende freie Timeline wurde dabei nicht
gestartet; deren aktiver Lesezweig ist weiterhin nur mit Fixtures geprüft.

Ein anschließender Lauf bestätigte den Export im Unterformat 2. Eine
separate lesende Diagnose fand zehn registrierte, inaktive Inhalte und
erreichte bei allen über `get_Performance()` eine echte
`TimelinePerformance`: Ausführungsstatus 0, Abschlussindikator `false`,
`get_CurrentEventInfo()` jeweils nicht vorhanden. Diese reale Teilprüfung
bestätigt die Getterkette bis zur fehlenden Ereignisinformation, aber keine
laufende Performance und keinen Timeline-Frame. Wieder blieb es bei einem
erlaubten alten Load, null verweigerten Loads, keiner gezählten
Speicheranforderung und zwölf unveränderten Dateien. Der eigene Prozess
und alle temporären Diagnoseskripte wurden sauber beendet bzw. entfernt.

Am 17. November 2026 wurden die verwendeten Schnittstellen auf RE2 Build
11636119 mit REFramework d1461375 lesend untersucht. Der fertige Leser
wurde danach in einer eigenen geschützten Instanz geprüft: am Titelbild
`scene_unavailable`, nach genau einem erlaubten Load des alten Slots 4
vom 11.11.2026 drei frische Proben mit steigenden Sequenzen. Die Szene lief
unter der eigenen nativen Menüpause des getrennten No-Peer-Tests aus #104.
Es gab **keine aktive Timeline, Kamera-Performance oder Filmwiedergabe**.
Die aktiven Performance-/Framezweige sind damit nur mit nachgebildeten
Quellen geprüft, nicht bei einer echten laufenden Zwischensequenz.

Die Probe zeigte `pause_requested=true` bei `pause_executed=false` und
keinem aktiven Ereignis. Diese Werte sind Indikatoren, kein Nachweis einer
angehaltenen Cutscene. Insbesondere beweist ein leerer Aktivsatz keinen
Stillstand. Es wurde keine Cutscene gestartet, übersprungen oder beendet.
Es gab keine gezählte Speicheranforderung, null verweigerte Loads und
zwölf bytegleiche Speicherdateien ohne neue Save-Datei. Die eigene Instanz
wurde geschlossen und sämtliche temporären Diagnoseskripte entfernt.

Weiter offen sind kurze Übergänge zwischen den Abfragen, tatsächliche
Start-/Skip-/Endereignisse, Filmplayer-Zeiten, die reale Abnahme freier/nicht
kamerageführter Timeline-Frames, Ereignisse während anderer Ladephasen, die gesamte
Szenenmatrix, Host-Anwendung und der Vergleich zweier echter Instanzen.
Für eine Pausenabnahme muss zunächst ein tatsächlich fortschreitendes
Ereignis vor und während der Pause gemessen werden. Weder KI/Physik noch
vollständige Weltgleichheit oder Cutscene-Synchronisation sind hiermit
abgenommen.
