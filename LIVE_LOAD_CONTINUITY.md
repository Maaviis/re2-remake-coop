# Fortlaufende Gegnerbeobachtung nach dem Laden

Dieser Beitrag behandelt [#86](https://github.com/Maaviis/re2-remake-coop/issues/86).
Die erste Bestätigung eines nativen Ladevorgangs hat weiterhin eine
120-Sekunden-Frist. Ein bereits bestätigter laufender Beobachter kann
anschließend denselben Ladevorgang weiter prüfen. Die Frische von Guard,
Ladekopf, Gegnerquelle und empfangenem Gastbeleg bleibt auf drei Sekunden
begrenzt. Ein höheres Ladealter verlängert keine dieser Fristen.

## Bindung und Fehlerfälle

Der Host merkt sich Lade-ID, vollständige ausgewählte Save-Referenz,
Observer-Laufkennung, nativen Ladebeginn, Anzahl erlaubter Ladeaufrufe
und Checkpoint. Gegner- und Ladekopfquelle haben jeweils ihre eigene
Bindung. `EnemyLiveFeed` nutzt den Fortsetzungsmodus erst nach erfolgreicher
Erstprüfung. Ein späterer Snapshot-Abruf desselben laufenden Beobachters
prüft dieselbe Bindung erneut. Ein gewechselter Observer oder Checkpoint
entfernt den Livezustand; ein solcher Stream wird nicht neu basiert.

Die Gastdiagnose merkt sich dieselben lokal verfügbaren Lade- und
Observermerkmale und verlangt weiter einen frischen Empfangsbeleg.
Native Sequenz und Beobachtungszeit dürfen nicht zurücklaufen.
Ein neuer Ladebeginn, eine andere Lade-/Policy-ID, ein anderer Slot,
Observer oder Checkpoint sowie zusätzliche Ladeaufrufe ergeben keine
gültige Fortsetzung. Schreibaufrufe, abgefangene Ladeanforderungen und
fehlende/abgelaufene Belege bleiben gesperrt.

Ein kurzzeitig fehlender oder nicht lesbarer Beleg entfernt den aktuellen
Livezustand. Frische Belege derselben weiterhin bestätigten Bindung erlauben danach
wieder neue Beobachtungen. Ein neuer Hostbeobachter
oder eine neu gestartete Gastdiagnose besitzt diese Bindung noch nicht
und kann einen bereits zu alten Ladevorgang nicht einfach übernehmen.
Wiederherstellung nach Prozessneustart und der gemeinsame Rejoin benötigen
weiterhin ihre gesonderte Lade-/Zustandsabnahme.

Das v1-Nachrichtenformat und die nativen HP-/Speicherfunktionen bleiben
unverändert. Der Fortsetzungsmodus ist eine interne Option der Leser;
die erste CLI-/Ladebarrierenprüfung behält ihr bisheriges Verhalten.
Die eigene Laufzeitbegrenzung eines Diagnosebefehls bleibt davon getrennt.

## Regressionen

197 Python-Tests und 18 Lua-Einstiegssuiten bestehen lokal. Die neuen
Host- und Gastregressionen scheiterten vor der Korrektur beim Überschreiten
der 120-Sekunden-Grenze. Sie prüfen unter anderem:

- unveränderte Erstprüfung und Ablehnung eines alten ungebundenen Ladens;
- frische Beobachtungen vor/nach der Grenze sowie bei 730 Sekunden;
- einen späten Snapshot desselben bestätigten Beobachters;
- Quellenverlust, Fristablauf und Wiederaufnahme derselben Bindung;
- gewechselte Lade-/Observer-/Checkpointdaten und native Sequenzrückläufe;
- weiterhin abgewiesene Speicheraufrufe, fremde Policies und alte Belege.

## Native Einzelinstanz-Messung am 16. November 2026

Geprüft wurden RE2 Steam Build 11636119, REFramework d1461375 und TDB 70.
Der Hostleser verarbeitete echte Gegner- und Ladekopfberichte. Eine lokale
Testhilfe erzeugte die Gastdatei; es gab weder eine Steam-Gegenstelle noch
eine zweite Spielinstanz. Installiert war die lesende Gastdiagnose ohne
HP-Anwender.

| Messung | Ladealter etwa | Befund |
|---|---:|---|
| Erfasste Baseline | 108 s | drei frische bestätigte Host-/Gastproben, aktive Menge 0 |
| Fortlaufende Prüfung | 150 s | fünf frische bestätigte Proben, aktive Menge 0 |
| Empfang nicht mehr erneuert | 154 s | Livezustand entfernt, `invalid_or_expired_receipt` |
| Empfang wieder erneuert | 155 s | fünf frische bestätigte Proben derselben Bindung |
| Später Snapshot | nach 155 s | vorhandene Hostbindung erneut bestätigt |
| Aktive Gastdiagnose | 412–413 s | fünf frische Proben mit fünf passenden aktiven Controllern |
| Neuer ungebundener Hostleser | nach 120 s | Erstprüfung weiterhin abgewiesen |

Die aktive Gastprüfung verwendete ausdrücklich simulierte Peerwerte aus
den echten nativen Gegnerdaten: Bei einem lebenden Gegner zeigte sie
Host-HP 769 und lokale HP 770 getrennt. Es erfolgte kein HP-Schreibaufruf;
die tatsächlichen lokalen HP blieben 770. Diese spätere Prüfung bestätigt
die lokale Gastfortsetzung mit aktiven Objekten und ersetzt keinen
laufenden Host-Gast-Test mit zwei Spielen.

Ein anfänglicher kalter Titelbefehl wurde vor jeder nativen Lesung mit
`title_not_ready` zurückgewiesen. Nach bestätigter Titelbereitschaft wurde
im selben Prozess ausschließlich der erlaubte alte Slot 4 vom 11.11.2026
geladen. Der Guard meldete insgesamt eine erlaubte Lesung, null abgefangene
Ladeanforderungen und keinen Speicheraufruf. Nach bestätigtem Ende des
eigenen Prozesses waren Originalordner/-konfiguration wiederhergestellt;
alle zwölf Save-Dateien blieben bytegleich, keine neue kam hinzu.

Alle Spielaktionen liefen über das Terminal. Laufzeitbelege und private
Testhilfen bleiben lokal. Die gemeinsame Abnahme mit zwei echten
RE2-/Steam-Instanzen und vollständige Kampagnensynchronisation stehen aus.
