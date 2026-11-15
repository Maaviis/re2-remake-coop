# Lesender Gegnerzustand

Der optionale Leser `re2_coop/enemy_state.lua` erfasst den begrenzten
Umfang `registered_enemy_contexts`. Er setzt keine Spielfelder und ruft
keine Lade-, Speicher-, Spawn-, Schadens- oder Todesmethode auf.
Er sendet keine Netzwerkereignisse und gibt kein Gameplay frei.

Ein Eintrag ohne laufenden Controller ist ausdrücklich **kein toter
oder entfernter Gegner**. Die Registry ist keine vollständige Liste
aller Gegner über die gesamte Kampagne.

## Native Quellen und Format

Der Leser ist auf RE2 und TDB 70 begrenzt. Vor seiner Erstellung prüft
er Getter-, Feld-, Parameter- und Rückgabetypen. Abgeleitete Kontext- und
Controllerklassen müssen die bestätigten Basistypen besitzen.

| Quelle | Getrennt erfasste Werte |
|---|---|
| `EnemyManager.EnemyList` | Anzahl und eindeutige GUIDs der registrierten Einträge, KindID |
| `EmCommonContext` | GUID, InheritID, Status, Eliminated, Position und Rotation |
| `RegisterEnemyInfo.ContextData` | Optionaler gespeicherter Datensatz: GUID/KindID, InheritID, HP/DefaultHP, Eliminated, rohe Flags, Karte/Gebiet und Transform |
| `RegisterEnemyInfo.Controller` | Optionaler laufender Controller: GUID/KindID, InheritID, aktiv/live/setup/loading/standby, zwei rohe Zustandsfelder und die eigene HitPoint-Komponente |
| `EnemyHitPointController` | Laufende HP/DefaultHP und das getrennte native IsDead-Flag |
| `EnemyManager.ActiveEnemyList` | Vollständig mit Registry, Aktivflag und konkretem Controllerobjekt abgeglichene aktive Menge |
| Ladekopf und Manager | Spiel-/Save-GUID, Szenario, Ladeort, Gesamtzahl getöteter Gegner und natives IsPausing |

Kontext, gespeicherte Daten und laufender Controller haben jeweils ein
eigenes `present`-Feld. Fehlt eine Quelle, enthält sie ausschließlich
`present:false`. Gespeicherte HP werden nie als laufende HP ausgegeben.
`is_live`, `is_dead`, `eliminated`, HP und Flags bleiben unabhängig; der
Leser erfindet daraus keine gemeinsame Todesregel. UInt32-Hochbits und
negative InheritIDs bleiben erhalten.

Ein Snapshot wird nach GUID sortiert. Leere/doppelte GUIDs, falsche
Objekttypen, widersprüchliche Identitäten, fehlende Pflichtwerte und
nicht endliche Transforms verhindern eine gültige Probe. Der Leser
kürzt die Registry nicht still ab: Mehr als 512 Einträge sind nicht
unterstützt. Er liest zweimal unmittelbar nacheinander und vergleicht
Werte sowie Szene, Spieler, Manager, Listen und erfasste Quellobjekte.
Eine Änderung ergibt Nichtverfügbarkeit. Das ist keine atomare Weltsperre.

## Installation für Entwickler

In einer isolierten Installation das Modul unter
`reframework/autorun/re2_coop/enemy_state.lua` ablegen und zusätzlich
`reframework/diagnostics/re2_coop_enemy_state_observer.lua` nach `autorun`
kopieren. Die Diagnose ist standardmäßig nicht installiert. Sie schreibt
alle sechs Updates die lokale Datei `reframework/data/re2_coop_enemy_state.json`.
Der Bericht trägt Quelle, TDB, Laufkennung, steigende Sequenz, lokale
Beobachtungszeit, Umfang und Verfügbarkeit. Bei Quellenverlust wird der
vorherige Zustand nicht weiter ausgegeben.

Ein späterer Verbraucher muss Frische, Lauf-/Prozess-/Sitzungsbindung
und Sequenzen prüfen. Dieser Beitrag enthält noch keinen solchen
Netzwerkverbraucher oder nativen Zustandsanwender.

## Nachweis am 15. November 2026

Eine lesende Typuntersuchung und anschließend eine frische Instanz mit
der fertigen Leserfassung liefen auf Steam Build 11636119,
REFramework d1461375 und TDB 70. Verwendet wurde ausschließlich der
freigegebene alte Slot 4 vom 11.11.2026 unter dem bestehenden Guard.
Die Guard-/Ladeanbindung blieb unverändert; dies ersetzt keine gemeinsame
Menü- oder Netzwerkabnahme.

Vor dem Laden meldete der fertige Leser erwartete Nichtverfügbarkeit.
Nach Laden bestätigten fünf frische Proben 55 eindeutige, sortierte GUIDs,
55 vorhandene Kontexte und denselben begrenzten Zustandsdigest. Der
native Gesamtzähler meldete 19 getötete Gegner. Die Berichtsdatei war
50.184 Bytes groß. In diesem Abschnitt waren **null aktive Controller
und null gespeicherte ContextData-Einträge** vorhanden. Die nativen
HP-/Todes-/gespeicherten Datenpfade sind damit nicht positiv abgenommen.

Beide isolierten Läufe hatten je genau eine erlaubte alte-Slot-Lesung,
keine abgefangene Ladeanforderung und keinen erfassten Speicheraufruf.
Nach bestätigtem Prozessende waren Originaldateien/-konfiguration
zurückgestellt; alle zwölf kontrollierten Save-Dateien blieben unverändert,
ohne neue Datei. Die Spielsteuerung erfolgte ausschließlich im Terminal.

Die Lua-Tests prüfen insbesondere getrennte laufende/gespeicherte HP,
Abwesenheit ohne erfundenen Tod, GUID-Hochbits und Eindeutigkeit,
fremde Controllerobjekte trotz gleicher GUID, aktive Mengen,
Quellen-/Objekt-/Szenenwechsel und Nichtverfügbarkeit. Alle 16
Lua-Einstiegssuiten bestehen lokal; die Lobby ruft zusätzlich ihren
separaten Menücheck auf.

## Weiterhin erforderlich

Aktive Gegner, verschiedene Gegnertypen und Bossphasen mit realen
HP-/Schadens-/Todesänderungen messen. GUID-/InheritID-Zuordnung nach
Neuladen, Streaming, Spawn und zwei getrennten Spielinstanzen prüfen.
Gespeicherte Gegner außerhalb der Registry ergänzen. Native Zustände
und Nebenwirkungen autoritativ anwenden und danach beidseitig vergleichen.

Der vorhandene Steam-Posenpfad akzeptiert ausdrücklich nur Posen und
höchstens 4096 Bytes pro Nachricht. Bereits diese Registry-Probe ist
größer. Vollständige Gegner-Snapshots benötigen deshalb ein dokumentiertes,
sitzungsgebundenes Übertragungsformat mit Fragmentierung, Fristen,
Integritätsprüfung und vollständigem Commit statt teilweiser Anwendung.
Der neue Leser erweitert den Posenpfad nicht stillschweigend.
