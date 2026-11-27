# Native Inventardetails und Schnellzugriffe

Dieser optionale Leser erweitert den [Inventarkern](LOAD_WITNESS.md) um
die tatsächlich bestätigten Item-Payloads und die Richtungszuordnungen
des aktuellen Spielers. Sein eigener Umfang heißt
`load_header_and_inventory_detail`. Beide Formate bleiben getrennt;
der Kernleser akzeptiert keine Detailprobe als Kernprobe und umgekehrt.
Ein gleicher Digest bestätigt ausschließlich die aufgeführten Werte.
Er gibt kein Gameplay frei und ist kein vollständiger Weltabgleich.

## Bestätigte Daten

Eine lesende Untersuchung auf RE2 Steam Build 11636119, REFramework
d1461375 und TDB 70 bestätigte die folgenden Typen und laufenden Werte:

| Bereich | Daten |
|---|---|
| Ladekopf und Inventarkern | Unveränderte Felder aus `LOAD_WITNESS.md`, einschließlich aller logischen Slots und Ausrüstung |
| Jeder vorhandene Slot | Letzter Waffentyp sowie eigene `inner`, `extra` und `stock`-Payloads |
| `InventoryManager.PrimitiveItem` | Item-, Waffen-, Waffenteile- und Munitionskennung sowie Menge |
| `InventoryManager.ItemExData` | ExUintData als UInt32, ExItemID, RogueWeaponLevel, IsInitialSet und InitialCount |
| `InventoryManager.StockItem` | Index, IsWeaponEquip und die getrennten geerbten Felder DefaultItem, AdditionalItem und ExData |
| Schnellzugriffe | Getrennte Haupt-/Nebengruppe, jeweils Anzahl und nach Schlüssel geordnete Slots; Up=0, Down=1, Left=2, Right=3 |

DefaultItem und AdditionalItem werden nicht zusammengezogen. Ebenso
werden die Slot-Getter `get_InnerData`/`get_ExtendData` nicht durch
angenommene Aliasbeziehungen zu den Stockfeldern ersetzt. Fehlende
Payloadobjekte sind ausdrücklich `present:false`; fehlende Pflichtfelder
eines vorhandenen Objekts sind ein Fehler. Leere, aber vorhandene Slots
bleiben von fehlenden Slots unterscheidbar. Auch ein Shortcut auf einen
leeren Slot wird erfasst. Die gespeicherten Waffentypen können von der
aktuellen Bestückung abweichen und werden separat gelesen.

Es werden die nativen Dictionary-Schlüssel abgefragt, nicht die Reihenfolge
einer Slotliste. Nicht bekannte oder nicht vollständig gezählte Einträge
ergeben keine gültige Probe. Der Leser prüft Getter-/Feldsignaturen,
Objekttypen und die vier Enumwerte. Die gesamte erweiterte Probe durchläuft
dieselben zwei unmittelbar aufeinanderfolgenden Abfragen und dieselben
Szenen-/Spieler-/Inventarprüfungen wie der Kern. Ändert sich ein erfasstes
Detail zwischen den Abfragen, bleibt die Probe unverfügbar. Das ist keine
atomare Sperre der Welt.

Die Untersuchung fand außerdem eine laufende `InventoryManager.SaveData`
mit zwei `inventory.Data`-Einträgen für unterschiedliche Überlebendentypen.
Diese Anzahl beweist weder zwei Spieler noch eine Itembox. Die gespeicherten
Datensätze, Effekt-/Rangflags und Itembox gehören noch nicht zum Detailformat.
Für andere Szenarien und Figuren müssen die Befunde gesondert geprüft werden.

## Installation und Verwendung

In einer isolierten Entwicklerinstallation das aktualisierte Modul
`reframework/autorun/re2_coop/load_state.lua` und zusätzlich
`reframework/diagnostics/re2_coop_inventory_state_observer.lua` als
Autorun installieren. Der Observer schreibt nur die lokale Datei
`reframework/data/re2_coop_inventory_state.json`. Er setzt keine
Spielfelder und ruft weder Lade- noch Speicherfunktionen auf.
Die Kernprobe lässt sich unabhängig davon weiterverwenden.

```powershell
python bridge/inventory_witness.py --data "<RE2>/reframework/data"
python bridge/inventory_witness.py --data "<RE2>/reframework/data" --request-id "<eigene Lade-ID>" --save-slot scenario:4 --allow-save-date 2026-11-11
```

Die zweite Variante benötigt den bereits beschriebenen Guard, Katalog
und die Ladeprobe aus `READONLY_LOAD.md`. Sie übernimmt deren eigene
Lade-ID, aktive Policy, Slot-/Szenariobindung und Fristen aus dem
Kernleser. Der Detailleser prüft zusätzlich die genaue Payloadstruktur,
Integer-/Boolwerte, UInt32-Grenzen und eindeutige, aufsteigende bekannte
Shortcut-Schlüssel. Er akzeptiert keine alte Kernprobe als Ersatz und
verwendet nach Quellenverlust keinen früheren Zustand. Die Terminalausgabe
enthält Metadaten und Digest, keine persönlichen vollständigen Itemdaten.

## Prüfstand und offene Arbeit

136 Python-Tests und elf Lua-Suiten bestehen lokal. Die Erweiterung prüft
insbesondere unterschiedliche Default-/Additional-Mengen, UInt32-Hochbits,
erhaltene Boolwerte, fehlende Payloads/Felder, ungültige Typen und Signaturen,
unvollständige Shortcut-Dictionaries, Änderung eines Zusatzfelds zwischen
den Lesevorgängen, neue Digests bei Payload-/Tastenänderung sowie
Quellenverlust, Sequenzwiederverwendung, Fristen und VM-Wechsel.

Die native Leseuntersuchung lud ausschließlich den erlaubten alten Slot
vom 11.11.2026 mit einer Leseanforderung, ohne abgefangene Ladeanforderung
oder erfassten Speicheraufruf. Nach Prozessende wurden Originalskripte und
Konfiguration zurückgestellt; zwölf Save-Dateien blieben unverändert,
keine neue erschien. Private Reflexionsdaten und Inventarwerte bleiben lokal.

Ein Startversuch brach vor der Lua-Initialisierung in `tier0_s64.dll` ab.
Zwei Abnahmen des fertigen Detailreaders meldeten am Titelbild korrekt
keinen verfügbaren Zustand, brachen dann aber beim Szenenladen mit
`0xc0000005` im vom Framework genannten NVIDIA-Modul `nvwgf2umx.dll` ab.
Die Ursache bleibt offen; das ist kein erfolgreicher Gameplay-Nachweis.
Nach jedem Abbruch wurden Originaldateien und zwölf unveränderte
Save-Dateien bestätigt. Windows protokollierte zeitgleich Ereignis 2004
für erschöpften virtuellen Speicher. Auch ein Kontrolllauf mit dem
unveränderten Kernleser aus #58 erreichte unter erneut gemeldetem
Speichermangel keinen Ladeabschluss innerhalb von 45 Sekunden. Dieser
eigene Testprozess wurde beendet und die Installation wiederhergestellt.
Zusätzlich fiel ein PowerShell-Start mit `OutOfMemoryException` aus.
Die genaue Verbindung zwischen Speichermangel und Grafiktreiberabbruch
ist nicht bewiesen. Weitere native Abnahmen wurden bis zu ausreichenden
Systemressourcen ausgesetzt; andere Anwendungen und Systemeinstellungen wurden
nicht verändert. Diese abgebrochenen Läufe liefern keinen
erfolgreichen nativen Nach-Laden-Nachweis. Die erfolgreiche Felduntersuchung
ersetzt diese Abnahme nicht. Diese Befunde bleiben getrennt vom früheren
abgefangenen-Fortsetzen-Absturzpfad aus #50.

Ein späterer frischer Hintergrundlauf am 15. November 2026 fand bei
rund 44 GiB freiem RAM und 52 GiB freiem virtuellen Speicher statt.
Der unveränderte fertige Reader meldete am Titelbild erwartungsgemäß
keinen verfügbaren Zustand und bestätigte nach dem Laden ausschließlich
des erlaubten alten Slots fünf frische Proben mit demselben Detail-Digest.
Es wurden 20 logische Slots bei 12 nutzbaren Plätzen und je vier
Haupt-/Neben-Shortcuts erfasst. Die JSON-Datei war 84.513 Bytes groß und
lag unter der bestehenden Grenze. Eine fremde Lade-ID wurde abgewiesen.
Der Guard protokollierte genau eine erlaubte Leseanforderung, null
abgewiesene Ladeanforderungen und keinen Speicheraufruf. Es gab keine
Tastatur-/Mauseingabe, keinen Fokuswechsel und keine Bildschirmaufnahme.
Nach Ende ausschließlich des eigenen Testprozesses wurden Originaldateien
zurückgestellt; alle zwölf Save-Dateien waren unverändert, keine neue
erschien. Damit ist der begrenzte Nach-Laden-Nachweis für diese Instanz
erbracht. Die genaue Ursache der früheren Abbrüche bleibt offen;
der erfolgreiche Lauf belegt keine Treiber- oder Fehlerpfadbehebung.

Weiterhin fehlen Itembox und andere Inventare, Inventar-Effektflags,
Aufnahme/Verbrauch/Transfer, autoritative Ereignisse und native
Zustandsanwendung. Auch Gegner, Kampf, Türen, Rätsel, Story und sämtliche
Zwischensequenzen benötigen eigene Leser und Anwendungspfade. Die
gemeinsame Dateivorprüfung bleibt bestehen. Weltstillstand, koordinierte
Ladebarriere, Prozess-/Linkbindung und Tests mit zwei echten Spielinstanzen
und Steam-Konten sind weiterhin erforderlich.
