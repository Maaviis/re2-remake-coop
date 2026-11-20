# Lesender Gegnerzustand

Der optionale Leser `re2_coop/enemy_state.lua` erfasst den begrenzten
Umfang `registered_and_stored_enemy_contexts`. Er setzt keine Spielfelder und ruft
keine Lade-, Speicher-, Spawn-, Schadens- oder Todesmethode auf.
Er sendet keine Netzwerkereignisse und gibt kein Gameplay frei.

Ein Eintrag ohne laufenden Controller ist ausdrücklich **kein toter
oder entfernter Gegner**. Die Registry ist keine vollständige Liste
aller Gegner über die gesamte Kampagne.

Der erweiterte Umfang ersetzt im noch nicht gemergten Entwurf den früheren
Registry-Umfang `registered_enemy_contexts`. Ein Verbraucher muss den genauen
Scope prüfen und darf die Formate nicht gleichsetzen.

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
| `EnemyManager.StoreDataStorage` | Eigenständige Aufzählung mit `stored_count` und nach GUID sortierten `stored_entries`, einschließlich Gegnern außerhalb der Registry |
| `EnemyHitPointController` | Laufende HP/DefaultHP und das getrennte native IsDead-Flag |
| `EnemyManager.ActiveEnemyList` | Vollständig mit Registry, Aktivflag und konkretem Controllerobjekt abgeglichene aktive Menge |
| Ladekopf und Manager | Spiel-/Save-GUID, Szenario, Ladeort, Gesamtzahl getöteter Gegner und natives IsPausing |

Kontext, gespeicherte Daten und laufender Controller haben jeweils ein
eigenes `present`-Feld. Fehlt eine Quelle, enthält sie ausschließlich
`present:false`. Gespeicherte HP werden nie als laufende HP ausgegeben.
`is_live`, `is_dead`, `eliminated`, HP und Flags bleiben unabhängig; der
Leser erfindet daraus keine gemeinsame Todesregel. UInt32-Hochbits und
negative InheritIDs bleiben erhalten.

`StoreDataStorage` bleibt von `ContextData` und laufenden Controllern
getrennt. Die Speichereinträge enthalten auch den gespeicherten Wince-Wert.
Eine GUID darf in beiden Quellen vorkommen; keine Quelle überschreibt die
andere. Gespeicherte Werte ersetzen keine Echtzeitwerte eines aktiven Gegners.

Ein Snapshot wird nach GUID sortiert. Leere/doppelte GUIDs, falsche
Objekttypen, widersprüchliche Identitäten, fehlende Pflichtwerte und
nicht endliche Transforms verhindern eine gültige Probe. Der Leser
kürzt die Registry nicht still ab: Mehr als 512 Einträge sind nicht
unterstützt. Er liest zweimal unmittelbar nacheinander und vergleicht
Werte sowie Szene, Spieler, Manager, Listen und erfasste Quellobjekte.
Eine Änderung ergibt Nichtverfügbarkeit. Das ist keine atomare Weltsperre.

Für den Speicher gelten ebenfalls höchstens 512 Einträge. `_count`,
`_freeCount`, Arraygröße und öffentliche Anzahl müssen zusammenpassen.
Freigegebene Slots mit negativem Hash werden übersprungen; sie sind kein
Todesereignis. Schlüssel und Daten-GUID müssen übereinstimmen, die gezählte
Menge muss vollständig sein. Dictionary, Array, Datenobjekte und native
Arrays werden in den Doppelvergleich einbezogen. Das geschlossene Array
und sein Laufzeitelement haben im bestätigten Build unterschiedliche
Typnamen und werden getrennt geprüft. HP-/Transform-Getter werden erst
nach Prüfung ihrer Arraytypen und der beobachteten Längen 3 beziehungsweise
10 aufgerufen. Primitive Arrayelemente werden nicht ungeprüft serialisiert.

## Installation für Entwickler

In einer isolierten Installation das Modul unter
`reframework/autorun/re2_coop/enemy_state.lua` ablegen und zusätzlich
`reframework/diagnostics/re2_coop_enemy_state_observer.lua` nach `autorun`
kopieren. Die Diagnose ist standardmäßig nicht installiert. Sie schreibt
alle sechs Updates die lokale Datei `reframework/data/re2_coop_enemy_state.json`.
Der Bericht trägt Quelle, TDB, Laufkennung, steigende Sequenz, lokale
Beobachtungszeit, Umfang und Verfügbarkeit. Bei Quellenverlust wird der
vorherige Zustand nicht weiter ausgegeben. Ein Skriptreset veröffentlicht
ebenfalls Nichtverfügbarkeit; dieses Verhalten ist mit Lua-Tests geprüft.
Bei teilweise geschriebenem JSON muss ein Verbraucher begrenzt erneut
lesen oder die Quelle als unverfügbar behandeln.

Ein späterer Verbraucher muss Frische, Lauf-/Prozess-/Sitzungsbindung
und Sequenzen prüfen. Dieser Beitrag enthält noch keinen solchen
Netzwerkverbraucher oder nativen Zustandsanwender.

## Historische Registry-Abnahme am 15. November 2026

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
HP-/Todes-/gespeicherten Datenpfade waren damit nicht positiv abgenommen.

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

## Erweiterte Speicher-Abnahme am 15. November 2026

Eine gesonderte Positionsuntersuchung bestätigte begrenzte native
Positionsänderungen. Nach Verlust der Raumzuordnung wurde die eigene
Figur an ihre protokollierte Ausgangsposition mit wieder korrekter
Raumkennung zurückgesetzt. Sie lieferte keinen aktiven Gegnernachweis,
fand aber 87 Einträge im eigenständigen `StoreDataStorage`. Die
Originalinstallation und zwölf unveränderte Saves wurden danach
bestätigt. Der private Bewegungshelfer gehört nicht zum Leser.

Der erste Abnahmeversuch der erweiterten Fassung meldete wegen des
abweichenden Dictionary-Elementnamens Nichtverfügbarkeit. Die Korrektur
bindet den beobachteten Array- und Elementtyp getrennt und lockert die
Prüfung nicht. Der Negativlauf wurde beendet, Originalinstallation und
zwölf unveränderte Saves wurden bestätigt.

Die korrigierte fertige Fassung wurde in einer neuen Instanz ohne
Bewegungs-/Schadenshelfer geprüft: vor dem Laden Nichtverfügbarkeit,
danach fünf frische Proben mit identischem begrenztem Digest. Sie erfassten
55 Registry- und 87 Speichereinträge; 51 GUIDs überschneiden sich,
insgesamt sind es 91 unterschiedliche Kennungen. Die früheren 55
Registry-GUIDs und die Ladekopfkennung stimmten nach dem Neustart und
erneuten Laden desselben alten Saves überein. Das ist ein Nachladevergleich
auf einem PC und Steam-Konto.

Gespeicherte HP lagen zwischen 0 und 999999. 40 Datensätze hatten null HP,
vier hatten positive HP unter dem Defaultwert. Das Eliminierungsflag war
bei allen falsch; der unabhängige Gesamtzähler meldete 19 Kills. Diese
Zahlen werden nicht in eine erfundene Zahl aktuell toter Gegner umgerechnet.
Aktive Controller und direkte `ContextData`-Einträge waren weiterhin null.
Die Datei war 117.483 Bytes groß. Genau eine erlaubte alte-Slot-Lesung,
keine abgefangene Ladeanforderung und kein erfasster Speicheraufruf;
nach Prozessende Originalinstallation zurückgestellt, zwölf Saves
unverändert, keine neue Datei. Alle Laufzeitaktionen erfolgten im Terminal.

## Aktive Controller, HP und Streaming am 16. November 2026

Der unveränderte Leser von Commit `26d6bc0` wurde in einer weiteren
isolierten Instanz auf Steam Build 11636119, REFramework d1461375 und
TDB 70 geprüft. Geladen wurde genau einmal der freigegebene alte Slot 4
vom 11.11.2026. Die Laufsteuerung benutzte den nativen ActionOrderer mit
begrenzten Einzelbefehlen und automatischer Freigabe. Der Weg über die
Treppe wechselte den gemeldeten Kartenbereich von 350 nach 112.
Es wurde keine zweite Spielinstanz oder Netzwerkverbindung verwendet.

Danach enthielt die aktive Liste fünf konkret zugeordnete Controller:
vier mit null HP, nativem `is_dead:true` und `is_live:false`, einer mit
770 HP, `is_dead:false` und `is_live:true`. Die KindIDs waren 0 und 2.
Eine aktive Listenzugehörigkeit bedeutet damit nicht automatisch Leben.
Der ausgewählte lebende KindID-0-Controller meldete `standby:true` und
keinen NoDamage-Schutz. GUID, InheritID, konkretes Controllerobjekt und
seine eigene HP-Komponente wurden vor jedem Eingriff neu geprüft.

Ein privater, nicht mitgelieferter Testhelfer rief die bestätigte
Instanzmethode `HitPointController.addDamage(System.Int32)` auf: zuerst
mit 1, anschließend einmal mit den verbliebenen 769 HP. Der Reader blieb
lesend. Je Tabellenzeile wurden fünf verschiedene frische Sequenzen
mit vollständigem Bericht gesichert, insgesamt 25 Proben.

| Phase | Aktive Menge | Laufende Ziel-HP | Native Ziel-Flags | Separate Speicher-HP |
|---|---:|---:|---|---:|
| Vor dem Eingriff | 5 | 770 | live=true, dead=false | 770 |
| Nach 1 Schaden | 5 | 769 | live=true, dead=false | 770 |
| Nach 769 Schaden | 5 | 0 | live=false, dead=true | 770 |
| Zurück im vorherigen Kartenbereich | 0 | Quelle fehlt | ausschließlich present=false | 0 |
| Nach erneutem Einstreamen | 5 | 0 | live=false, dead=true | 0 |

Die gesamte Registry blieb bei denselben 55 GUIDs, der separate Speicher
bei 87 Einträgen und der Ladekopf gleich. Beim erneuten Einstreamen hatte
das Ziel dieselbe GUID, aber andere konkrete Controller- und
HP-Objektadressen. Damit ist diese einzelne native Streamingfolge
beobachtet; Zuordnung zwischen zwei Spielinstanzen bleibt erforderlich.

Der Gesamtkillzähler blieb in allen fünf Phasen bei 19. Kontext- und
Speicher-Eliminierungsflag des Ziels blieben falsch. Der Versuch misst
HP-Komponentenaufrufe an einem gestreamten Standby-Controller.
Reguläre Treffer, Killverursacher, Animationen, Wince, KI-Reaktionen und
weitere Todesnebenwirkungen sind weiter gesondert zu prüfen.

Der Guard meldete eine erlaubte alte-Slot-Lesung, keine abgefangene
Ladeanforderung und keinen erfassten Speicheraufruf. Kamera und
Bewegungsfreigabe wurden zurückgelesen, der zugeordnete Prozess beendet
und die Originalordner/-konfiguration wiederhergestellt. Alle zwölf
Save-Dateien blieben bytegleich, ohne neue Datei. Rohberichte,
Objektadressen und private Testhelfer bleiben lokal und werden nicht versioniert.

Ein gesonderter Befund ist in
[Issue #86](https://github.com/Maaviis/re2-remake-coop/issues/86) erfasst:
Der fortlaufende Verbraucher verwendet weiterhin die 120-Sekunden-Grenze
des Ladebelegs. Im Versuch waren Guard und Gegnerbericht etwa 0,8 Sekunden
alt und verfügbar, das Laden etwa 730,8 Sekunden alt; `for_load` wies es
ab. Die Dauerbeobachtung benötigt eine fortlaufend geprüfte Bindung an den
bestätigten Ladevorgang.

## Weiterhin erforderlich

Reguläre Treffer- und Todesnebenwirkungen, verschiedene Gegnertypen und
Bossphasen messen; Killverursacher und Statistik getrennt abgleichen. GUID-/InheritID-Zuordnung nach
Neuladen, Streaming, Spawn und zwei getrennten Spielinstanzen prüfen.
Weitere gespeicherte Felder wie Erstposition, Zeitwerte, SupportItem-,
UniqueParam- und Effekt-/Stamp-Daten sowie Gliedmaßen-/KI-/Aktionszustände
fehlen. Der gemeinsame Weltzustand ist nicht vollständig erfasst. Native
Zustände und Nebenwirkungen müssen autoritativ angewandt und danach
beidseitig verglichen werden.

Der vorhandene Steam-Posenpfad akzeptiert ausdrücklich nur Posen und
höchstens 4096 Bytes pro Nachricht. Bereits diese Registry-Probe ist
größer. Die getrennten Entwürfe #73 und #74 ergänzen dafür ein dokumentiertes,
sitzungsgebundenes Übertragungsformat mit Fragmentierung, Fristen,
Integritätsprüfung und vollständigem Commit. Dessen Anwendung zwischen
zwei echten Spielinstanzen bleibt zu messen.
Der neue Leser erweitert den Posenpfad nicht stillschweigend.
