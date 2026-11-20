# Native Gegner-KI-Flags getrennt beobachten

Eine Mitgliedschaft in `ActiveEnemyList` beweist keine laufende Gegner-KI.
Der in [DEATH_OBSERVER.md](DEATH_OBSERVER.md) beschriebene Null-HP-Versuch
hat diese Grenze an einem echten Kampagnengegner gezeigt. Für zwei räumlich
getrennt handelnde Spieler muss der Host später nachweisen, dass die
relevanten Gegner beider Spielerbereiche tatsächlich simuliert werden.

## Opt-in-Erweiterung des Zustandslesers

`require('re2_coop.enemy_state').new({include_activity=true}).capture()`
ergänzt den vorhandenen lesenden Gegnerzustand. Der unveränderte Aufruf
`new()` benötigt keine zusätzlichen KI-Schnittstellen und behält die
bisherige Berichtsstruktur. Unbekannte Optionen und falsche Optionstypen
werden abgewiesen.

Die zusätzliche Metadatenprüfung verlangt RE2/TDB 70 und die gemessenen
Feld-/Methodentypen einschließlich der statischen Spielerkarten-Getter.
Es werden keine Hooks, Setter, Lade-, Speicher- oder Netzwerkoperationen
registriert oder ausgeführt. Die Diagnose verwendet ausschließlich die
abgegrenzten Zustands-Getter und die bisherige native Objektprüfung.

Das zusätzliche Wurzelfeld `activity` enthält:

- `scope=native_enemy_ai_flags`;
- `player_map` und `player_area` aus den nativen LastPlayerStay-Werten.

Bei einem vorhandenen Controller enthält `live.activity`:

- `think_enabled` aus `get_ThinkEnable`;
- `last_map` und `last_area` aus dessen LastStayScene-Werten;
- `think.present` sowie bei vorhandenem Denkobjekt dessen konkrete
  Klasse und den rohen `get_IsLive`-Wert.

Die bereits vorhandenen Werte `live.active`, `live.standby`,
`live.loading`, `live.setup`, HP-/Lebensflags und `paused` bleiben getrennt.
Ein fehlender Controller oder ein fehlendes Denkobjekt erzeugt keine
erfundenen Lebens-, Todes- oder Simulationswerte. Insbesondere ist weder
`think_enabled=true` noch `think.is_live=true` ein Nachweis für ausgeführte
KI-Entscheidungen. LastStay-Werte beschreiben auch keine vollständig
geladene oder für einen zweiten Spieler freigegebene Streaming-Region.

Der Leser erfasst den gesamten Zustand zweimal. Unterschiedliche
Objektidentitäten, Denkobjekte, Karten, Flags oder andere Zustandswerte
verwerfen die Probe. Das Denkobjekt wird dabei zusätzlich zur bestehenden
Controller-/HP-Identität verglichen. Auch diese Prüfung garantiert keine
atomare Engine-Transaktion über beliebige Threads hinweg.

## Getrennte lokale Diagnose

Die optionale Datei `reframework/diagnostics/re2_coop_enemy_activity.lua`
veröffentlicht alle sechs Updates `re2_coop_enemy_activity.json`:
Schema 1, Quelle RE2/TDB 70, Umfang, VM-Laufkennung, Sequenz, Zeitpunkt,
Verfügbarkeit, Grund und bei Erfolg den erweiterten Zustand. Ein Lade-,
Lesefehler oder Reset entfernt den zuvor verfügbaren Zustand aus dem
Bericht. Nach einem Reset veröffentlicht dieselbe Diagnose nicht weiter.

Die Datei ist im installierten Nutzerpaket nicht aktiviert. Ihr erweitertes
Format ist kein neuer Netzwerkvertrag: Der vorhandene Gegner-/Steam-Pfad
behält seinen bisherigen Bericht. Ein künftiger Verbraucher muss zusätzlich
Prozess, Load, Checkpoint und Steam-Sitzung binden sowie Aktualität,
Sequenzfortschritt und Quellverlust prüfen. Ein gespeichertes JSON-Dokument
nach Prozessende darf keine Spielfreigabe erteilen.

## Abnahmegrenzen

Die Lua-Prüfungen decken die unveränderte Standardschnittstelle ohne
optionale Metadaten, vorhandene/fehlende Denkobjekte, unabhängige Flags,
wechselnde Objektidentitäten/Karten/Flags, ungültige Metadaten und die
Invalidierung des Diagnoseexports ab. Alle 20 Lua-Suiten bestehen.

Am 18. November 2026 wurde die unveränderte geschützte Runtime 4494ef2 mit
einer temporären, bytegleichen Kopie des erweiterten Lesers unter einem
privaten Modulnamen geprüft. Dadurch blieben der installierte Standardleser
und sein Steam-Bericht unverändert. Nur der freigegebene alte Slot 4 vom
11.11.2026 wurde geladen; der bekannte kurze Weg wurde über das Terminal
abgelaufen. Der private Treiber bot keine Kampf- oder KI-Schreibbefehle an.

Neun unterschiedliche Berichtssequenzen über zwei Sekunden ergaben:

| Beobachtung | Ergebnis |
|---|---|
| Spieler-LastStay-Werte | Karte 112, Bereich 5 |
| Aktive Controller | Fünf, alle mit `think_enabled=false` und `standby=true` |
| Denkobjekte | Fünf vorhanden, davon eines mit `is_live=true` |
| Lebender gewöhnlicher Zombie | HP unverändert 770, Controller-Lebensflag wahr, Todesflag falsch; Denkobjekt ebenfalls lebend, Denklogik dennoch deaktiviert |
| Controller-LastStay-Karten | 119 beziehungsweise 239; diese Werte sind keine Streaming-Freigabe |
| Globaler Killzähler | Unverändert 19 |
| Standardbericht | Nach Entfernen der zusätzlichen KI-Felder identisch zur unabhängig gelesenen nativen Abschlussprobe |
| Speicherschutz | Ein erlaubter Load, keine Lua-Speicheranforderung; frischer nativer Guard mit zehn Writerzählern null, eine Sekunde älter als die letzte Zustandsprobe |
| Dateivergleich und Rückbau | Zwölf bytegleiche Dateien, keine neue Save-Datei; eigene Instanz geschlossen und temporäre Skripte entfernt |

Die [bereinigten Messwerte](validation/native-enemy-activity-2026-11-18.json)
enthalten aggregierte Controllergruppen und den SHA-256 des privaten
Rohberichts. Persönliche Save-/Steam-Kennungen und Prozessadressen sind
nicht enthalten. Der Leser unterscheidet die gemessenen Flags; eine positive
KI-Freigabe oder tatsächlich ausgeführte Entscheidung wurde nicht beobachtet.

Weiter offen sind ein tatsächlich arbeitender Gegner, ein natürlicher
Treffer, ein positiver nativer Todescallback und sämtliche Todesnebenwirkungen.
Danach ist die Host-Simulation für beide Spielerbereiche zu prüfen.
Die vorliegende Diagnose schaltet keine KI ein und ist keine bestandene
Kampf-, Streaming- oder Zwei-Spieler-Synchronisation.
