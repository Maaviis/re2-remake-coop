# Cutscene-Aufnahme und Replay

## Zu zweit aufzeichnen

Auf beiden PCs denselben Steam-Build installieren und die Koop-Kampagne normal starten. Der Host zeichnet während der freigegebenen Szenensynchronisierung automatisch auf. Der Gast braucht dafür keinen zusätzlichen Schalter. Bei einem Fehler Szene, Hostaktion und Uhrzeit merken.

Im RE2-Spielordner des Hosts liegt die Aufnahme neben der gemeinsamen Zeitleiste unter `reframework/data/re2_coop_logs/<Sitzungs-ID>/scene-*.jsonl`. Für eine Untersuchung die Datei der betroffenen Szene und `timeline.jsonl` aus demselben Ordner sichern. Die Aufnahme enthält den lokalen Szenenzustand des Hosts und die vom Host tatsächlich empfangene, gültige Gastansicht. Der Zeitabstand stammt von der monotonen Uhr des Hosts. Dadurch lässt sich auch festhalten, ab wann eine Partnerbestätigung fehlte. Die Ursache für den Verlust ergibt sich gegebenenfalls aus der Zeitleiste.

Eine Datei umfasst eine Szene und deren Auftreten innerhalb eines Startversuchs. Bei einer Änderung der Bindung oder einem fehlenden lokalen Szenenbeleg beginnt der nächste belegte Abschnitt in einer eigenen Datei. Grenzen je Abschnitt sind zehn Minuten und 180 Zustandswechsel, je Bridge-Prozess 128 Dateien. Vollständige Zeilen einer abgebrochenen Aufnahme bleiben lesbar. Der Bericht gibt für diesen Fall `partial` aus. Frühere reine Textlogs enthalten die erforderlichen Zeit- und Lückenbelege nur teilweise.

## Mit simuliertem Gast wiedergeben

1. Einen geschützten Solotest in einer leeren Host-Lobby starten. Die Solokampagne verwendet Leon A auf Normal. Ein Replay braucht dieselbe erreichbare Szene und dasselbe Auftreten. Für den ersten Introtest bei der Trucker-Szene auf die Ankunft des Gasts warten.
2. PowerShell im RE2-Spielordner öffnen. Den Pfad zur Aufnahme einsetzen. Die erste Zeile zeigt aufgezeichnete Hostaktionen und Gastantworten, die zweite aktiviert genau diese Aufnahme für den gerade laufenden Solostart.

~~~powershell
.\re2-coop\runtime\python.exe .\re2-coop\session_replay.py "C:\Tests\scene-aufnahme.jsonl"
.\re2-coop\runtime\python.exe .\re2-coop\session_replay.py "C:\Tests\scene-aufnahme.jsonl" --game .
~~~

3. Frühere Szenen bei Bedarf mit der üblichen Solosteuerung durchlaufen. In der Zielszene übernimmt das Replay die Ankunft und Stimmen des Gasts. Die Hostseite selbst bedienen, etwa mit Esc und Leertaste einen Skip anfragen. Jede Gruppe in der Aufnahme gilt für einen bestimmten Hostzustand einschließlich Abstimmungsrunde und Entscheidung. Ihre Zeitabstände laufen ab dem beobachteten Eintritt in diesen Zustand. Bei einer abweichenden Runde, einer aufgezeichneten Lücke oder nach dem Ende des Zeitfensters erhält der Host keine Gaststimme.
4. Die HUD-Zeile zeigt den Replay-Zustand. F10 beendet die Wiedergabe und gibt die Gaststeuerung wieder frei. Im REFramework-Log stehen die Wechsel unter `RE2_COOP_REPLAY`. Zum Wiederholen einen neuen geschützten Solotest starten und die Aufnahme erneut aktivieren.

Ein Replay erlaubt den Vergleich des beobachteten Skip-Verhaltens zwischen Builds. Es rekonstruiert weder den internen Zustand des anderen PCs noch einen Steam-Ausfall. Ob derselbe Fehler wieder auftritt, muss der Test zeigen.
