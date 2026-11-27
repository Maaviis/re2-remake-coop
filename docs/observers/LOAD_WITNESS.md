# Nativer Ladekopf und Inventarkern

Der optionale Beobachter liefert tatsächlich im Spiel gelesene Daten für
die Vorbereitung der gemeinsamen Ladebarriere. Sein fester Umfang heißt
`load_header_and_inventory_core`. Er bestätigt weder einen vollständigen
Weltzustand noch eine Gameplay-Freigabe und wendet keine Zustände an.

## Technischer Befund

Die Untersuchung auf RE2 Build 11636119, REFramework d1461375 und TDB 70
hat einen temporären `SaveDataManager.GameSaveDataValue.GameSaveDataList`
mit 32 typisierten Datenblöcken gezeigt. Beim erlaubten alten Ladevorgang
enthielt sie unter anderem folgende Gruppen:

| Gruppe | Bestätigte native Datentypen |
|---|---|
| Fortschritt und Ereignisse | `GlobalUserDataManager.GameSaveData`, `ScenarioSequenceManager.GameSaveData`, `PurposeManager.GameSaveData`, `TimelineEventManager.GameSaveData` |
| Gegenstände und Inventar | `ItemManager.SaveData`, `InventoryManager.SaveData`, `ItemLockerManager.GameSaveData` |
| Welt und Akteure | `GimmickSetManager.GameSaveData`, `PlayerManager.GameSaveData`, `NpcManager.GameSaveData`, `ActorManager.GameSaveData`, `EnemyManager.GameSaveData` |
| Ladekopf | `MainFlowManager.GameHeaderSaveData` |

Das sind bestätigte Typen und keine bereits synchronisierten Inhalte.
Nach dem Laden war die logische Listengröße null, obwohl das interne
Array weiterhin Platz für die vorherigen Einträge hatte. Die Arraygröße
darf deshalb nicht als aktuelle Datenmenge interpretiert werden. Der
beobachtete `get_GameSaveDataHash` blieb vor und nach dem Laden gleich.
Er wird nicht als Digest des geladenen Weltzustands verwendet; seine
genaue Bedeutung ist damit nicht vollständig bestimmt.

Der neue Beobachter liest stattdessen den bestehenden Ladekopf und die
laufende `app.ropeway.survivor.Inventory` am aktuellen Spielerobjekt.
Dabei wurden sowohl die nativen Getter als auch ihre Typen geprüft.

## Erfasste Daten und Grenzen

`re2_coop/load_state.lua` prüft unterstütztes Spiel, TDB und die verwendeten
Getter-/Feldsignaturen. Es verlangt einen abgeschlossenen Szenenladevorgang,
verlassenen Titel-/Ladeflow, freien Save-Manager, geschlossene vier
Titel-/Lademenüs sowie ein vorhandenes Spieler- und Inventarobjekt.
Alle Abfragen laufen außerhalb nativer Hooks in `UpdateBehavior`.

Zwei direkt aufeinanderfolgende Abfragen müssen dieselben Daten und
dieselben lokalen Spieler-/Inventarobjekte ergeben. Objektadressen werden
nur intern für diesen Vergleich verwendet. Ein fehlender, ungültiger oder
zwischenzeitlich geänderter Wert erzeugt einen nicht verfügbaren Befund.
`false` bleibt ein boolescher Wert und wird nicht durch eine Ersatz-Null
verdeckt. Das ist keine Sperre oder atomare Momentaufnahme der ganzen Welt.

| Bereich | Erfasste Werte |
|---|---|
| `checkpoint` | Szenario, ursprünglicher Überlebendentyp, Schwierigkeit, Ladeort, gespeicherte Kartenkennung, GameGUID und SaveGUID |
| `inventory` | Aktueller Überlebendentyp, Rolle, nutzbare Kapazität und vollständige logische Slotliste des Getters |
| Jeder Slot | Stockindex, Slottyp, Gegenstands-/Waffen-/Munitionskennung, Waffenteile, native Menge sowie Stock-, Leer-, Zwangsleer-, Breiten-, Tot-Slot- und Unendlich-Flags |
| `equipped` | Getrennte Kernwerte von Haupt-, Neben- und persönlichem Slot; fehlendes Objekt ausdrücklich als `present:false` |

Die interne Slotliste kann größer als die nutzbare Kapazität sein.
Reservierte oder breite Slots werden nicht abgeschnitten oder als eigene
neue Gegenstände zusammengezählt. GUIDs werden aus ihren bestätigten
32-/16-/16-Bit- und acht Byte-Feldern formatiert. Der überlappende native
64-Bit-Wert wird nicht über eine Gleitkommadarstellung übertragen.

`saved_map` und `location` beschreiben den Ladekopf, keine vollständige
laufende Raum-/Szenenidentität. Zusätzliche Itemdaten, Shortcut-Zuordnung,
Itembox und andere Inventare fehlen in diesem Kernumfang. Der getrennte
[Detailumfang](INVENTORY_WITNESS.md) ergänzt Item-Payloads und Shortcuts,
ohne das Kernformat zu ändern. Ebenso fehlen Gegner, Gesundheit,
Türen, Rätsel, Weltgegenstände, Flags, Ereignisreihenfolge, laufende
Zwischensequenzen und weitere Weltdaten. Ein gleicher `evidence_digest`
bedeutet ausschließlich gleiche Werte des oben aufgeführten Umfangs.

## Installation und Terminal

Für die vorhandene isolierte Entwicklerprobe das Modul
`reframework/autorun/re2_coop/load_state.lua` installieren und
`reframework/diagnostics/re2_coop_load_state_observer.lua` zusätzlich in
den Autorun-Ordner kopieren. Die Diagnose schreibt nur die lokale Datei
`reframework/data/re2_coop_load_state.json`. Sie ruft keine native
Lade-/Speicherfunktion auf, setzt keine Felder und sendet keine Nachrichten.

Für die an eine Lade-ID gebundene Prüfung müssen außerdem Guard,
Ladeprobe und nativer Katalog aus [READONLY_LOAD.md](../campaign/READONLY_LOAD.md)
laufen. Deren Speicher-/Löschsperre gehört weiterhin ausschließlich in
eine gesicherte Testinstallation, nicht in eine normale Spielrunde.

```powershell
# Rein lesender Status; am Titelbild erwartungsgemäß Exitcode 1:
python bridge/load_witness.py --data "<RE2>/reframework/data"
# Erlaubten alten Spielstand mit der bestehenden Probe laden:
python bridge/readonly_save_control.py --data "<RE2>/reframework/data" --allow-save-date 2026-11-11 --load --wait 45 scenario:4
# Danach die von diesem Befehl ausgegebene ID verwenden:
python bridge/load_witness.py --data "<RE2>/reframework/data" --request-id "<eigene Lade-ID>" --save-slot scenario:4 --allow-save-date 2026-11-11
```

`LoadStateFile` akzeptiert nur höchstens drei Sekunden alte, gültige
Samples. Ein Sequenzrücksprung oder geänderte Daten bei gleicher Sequenz
werden abgewiesen. Ein Dateifehler verwendet keinen früheren guten
Zustand als Ersatz. Die Terminalausgabe enthält den Umfang und Digest,
keine vollständigen persönlichen Inventar- oder GUID-Daten.

`for_load` verlangt zusätzlich einen frischen vollständigen Guard-Status,
die eigene native Lade-ID und dieselbe aktive Policy, `scene_loaded`,
passenden Slot und Szenario, kein abgefangenes Laden oder Schreiben und
ein Sample nach dem Start dieser Anforderung. Nach 120 Sekunden verfällt
die Ladeanforderung für diesen Nachweis. Ein abgewiesener anderer Befehl
ersetzt den ursprünglichen Ladeabschluss nicht. Eine neu akzeptierte
Policy oder ein anderer Observer-Lauf für dieselbe Lade-ID invalidiert
die Bindung. Die Dateiprüfung beweist kein aktuelles Prozess-/Steam-Leben;
der spätere Koordinator muss zusätzlich den tatsächlich laufenden Prozess,
den verifizierten Link und dessen Epoche binden.

## Prüfung und nächster Schritt

131 Python-Tests und elf Lua-Suiten prüfen den gemeinsamen Stand mit
bySenoms abgegrenztem Gast-Fristfix aus
[#56, 8536fea](https://github.com/Maaviis/re2-remake-coop/commit/8536fea37a51e6881c01ec16f663916111085c6e).
Die neue Suite prüft unter anderem Schnittstellenabweichungen, fehlende
Objekte/Werte, Objektwechsel bei gleichem Inhalt, Änderungen zwischen
Abfragen, falsche Boolwerte, GUID-Hochbits, zusätzliche interne Slots,
Quellenverlust, alte Samples, Policy-/ID-Wechsel und VM-Wechsel.

Ein frischer nativer Hintergrundlauf am 15. November 2026 bestätigte
fehlende Verfügbarkeit am Titelbild und anschließend den an die eigene
Lade-ID gebundenen Befund für ausschließlich den erlaubten alten Slot.
Fünf gültige Samples hatten steigende Sequenzen und denselben Kerndigest;
eine fremde Lade-ID wurde abgewiesen. Es gab genau eine native
Leseanforderung, keine abgewiesene Ladeanforderung und keinen erfassten
Speicheraufruf. Es wurden weder Eingaben noch Bildschirmaufnahmen benötigt.
Nach bestätigtem Prozessende wurden Originaldateien wiederhergestellt;
alle zwölf Speicherdateien waren unverändert, keine neue erschien.
Private Messwerte und Reflexionsprotokolle bleiben lokal.

Die gemeinsame Dateivorprüfung wird durch diesen Teilnachweis nicht
abgeschwächt. Für einen portablen gemeinsamen Spielstand und die
Ladefreigabe fehlen weiterhin vollständige native Zustandsleser,
Stillhalten beider Welten, über den bestätigten Versuch koordinierte
Ladeanforderungen, Zustandsanwendung und Tests mit zwei echten Instanzen.
Kampagnenmenü und der frühere Absturzpfad bleiben offen. Alle Anforderungen
aus [STATUS.md](../project/STATUS.md) behalten ihren bisherigen Umfang.

## Fortlaufende Verbraucher

Die erste `for_load`-Bestätigung behält ihre 120-Sekunden-Ladefrist.
Der Livebeobachter kann danach eine intern gemerkte, unveränderte
Ladebindung mit weiterhin frischen Guard-/Quellbelegen prüfen.
[Fortlaufende Ladebindung](../campaign/LIVE_LOAD_CONTINUITY.md) beschreibt Bindung,
Fehlerfälle und die native Einzelinstanz-Messung. Ein neu erzeugter Leser
besitzt diese Bindung noch nicht.
