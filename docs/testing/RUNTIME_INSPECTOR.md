# Lokale Laufzeitdiagnose

Aus dem Checkout bei bekanntem RE2-Spielordner starten. Ohne `--watch` liefert der Befehl genau ein JSON-Objekt. Mit `--watch` schreibt er eine JSON-Zeile pro Sekunde. Strg+C beendet die Abfrage.

~~~powershell
python tools/runtime_inspector.py --game "D:\SteamLibrary\steamapps\common\RESIDENT EVIL 2  BIOHAZARD RE2" --watch
~~~

Die Abfrage liest die vorhandenen lokalen Belege für Lobby, native Kampagnenpause und beide Posen. Jede Quelle hat eine eigene Zeit und einen Zustand. Ein frischer Bridge-Heartbeat kann einen abgelaufenen Bewegungsbeleg enthalten. Der Inspektor zeigt in diesem Fall `observation: expired` und lässt die Position weg. Die Momentaufnahme umfasst getrennte Dateilesungen und kann während eines Szenenwechsels unterschiedliche Zeitstände zeigen.

## Modell und Animation im isolierten Entwicklertest

Bei geschlossenem RE2 die [optionale Sonde](../../reframework/diagnostics/re2_coop_runtime_inspector.lua) in den Ordner `reframework/autorun/` des Testprofils kopieren. RE2 über Steam starten und dieselbe Abfrage ausführen. Nach dem Test RE2 schließen und die kopierte Sonde entfernen. Der letzte Beleg unter `reframework/data/re2_coop_dev_inspector.json` läuft nach drei Sekunden ab.

Die Sonde liest unter RE2 TDB 70 höchstens einmal pro Sekunde und Figur. Sie erhält die Objekte direkt vom laufenden Koop-Renderer. Solange er keine Kampagnenfigur oder Vorschau aktualisiert, bleibt der Rendererbeleg aus oder läuft ab. Ein leeres Teilobjekt bedeutet, dass für diese Rolle in der betreffenden Sekunde keine Abtastung vorlag. `renderer.player` bezeichnet die lokale Figur, `renderer.partner` die Figur der gemeinsamen Kampagne und `renderer.preview` die Solovorschau. Je nach vorhandener Komponente meldet die Sonde das DrawSelf-Flag, Mesh-Bereitschaft und Modellkennung, aufgebaute Gelenke sowie Bank, Clip und Frame des dominanten Animationsknotens. DrawSelf ist ein Engine-Flag. Für die tatsächliche Sichtbarkeit in der Kamera braucht es die Beobachtung im Spiel.

Fehlt die Sonde, funktionieren Lobby- und Posenabfrage weiterhin. Alle fünf Quellen stammen vom betrachteten PC. Netzwerkpose und tatsächlich auf diesem PC gerendertes Partnermodell lassen sich so getrennt prüfen. Die Abfrage gibt nur die ausgewählten Diagnosefelder aus und öffnet keinen Netzwerkport.
