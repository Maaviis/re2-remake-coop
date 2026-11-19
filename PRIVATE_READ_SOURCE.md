# Private Kopie liefert zwei native Leseantworten

Die geschützte Einzelinstanz-Probe vom 19. November 2026 bestätigt einen
begrenzten nächsten Schritt: Nach dem ursprünglichen erfolgreichen
Steam-Leseabschluss liefert eine vorab geprüfte private Kopie dieselben Bytes
in den Antwortpuffer. Anschließend ist der alte Slot 4 geladen. Das ist ein
Quellennachweis an der Antwortgrenze, noch keine Dateisystemisolation.

## Ausdrückliche Aktivierung und Umfang

Die zusätzliche Option verlangt `RE2_COOP_STORAGE_READ_TRACE=1`,
`RE2_COOP_STORAGE_READ_DIGEST=1` sowie drei Startvariablen:

| Variable | Inhalt |
|---|---|
| `RE2_COOP_PRIVATE_READ_FILE` | Absoluter Pfad zur privaten `data004Slot.bin` |
| `RE2_COOP_PRIVATE_READ_SHA256` | Erwarteter SHA-256-Wert, 64 kleine Hexzeichen |
| `RE2_COOP_PRIVATE_READ_REQUEST` | Vorab bestimmte Ladeanforderung, 32 kleine Hexzeichen |

Die vorhandene Startkennung und die tatsächliche Prozess-ID binden die
Konfiguration zusätzlich. Die Quelle wird einmal vor der Hook-Anbindung
rein lesend geöffnet, auf kanonischen Pfad, Dateityp und exakt 2.296.640 Bytes
geprüft und nach erfolgreichem Hashvergleich als unveränderliche RAM-Kopie
gehalten. Reparse-Ziele und abweichende aufgelöste Pfade werden abgewiesen.
Im Hook gibt es keinen Zugriff auf die Quelldatei. Ohne Aktivierung liest der
Publisher auch keine zusätzliche Lease-Datei.

Eine maximal 512 Bytes große Lease-Datei im lokalen REFramework-Datenordner
wird außerhalb der Steam-Hooks ausgewertet. Sie enthält sieben LF-getrennte
Zeilen: `RE2_PRIVATE_SOURCE_LEASE_V1`, Startkennung, Ladeanforderung, PID,
Unix-Ausstellungszeit, `639300365010000000` und `1:4:1`. Zusätzliche Zeilen,
abweichende Bindungen, zukünftige oder über drei Sekunden alte Ausstellung
werden abgewiesen. Die Lease gilt höchstens bis Ausstellung plus fünf
Sekunden; eine ungültige Erneuerung oder inaktive native Schreibsperre
entzieht die Freigabe. Der private Testtreiber erneuert sie während des Loads.

Nur eindeutig zugeordnete, erfolgreiche Originalabschlüsse für den exakten
bekannten Schlüssel `./win64_save/data004Slot.bin`, Offset null und die volle
Dateigröße kommen infrage. Höchstens zwei unterschiedliche native Anfragen
werden verarbeitet. Andere Dateien bleiben unberührt; Duplikate und
abweichende Bereiche werden abgewiesen. Die originale Steam-Anfrage, ihre
asynchrone Kennung und der Abschlussaufruf laufen weiterhin tatsächlich ab.
Der Wrapper erfindet weder Rückgabewerte noch Callbacks.

Vor jeder Übernahme muss der ursprüngliche Antwortpuffer bereits denselben
SHA-256-Wert besitzen. Nach diesem Vergleich wird die Lease erneut geprüft.
Die gesamte Zielregion muss committed und bereits schreibbar sein; Guard-,
ausführbare und nur lesbare Seiten werden abgewiesen. `WriteProcessMemory`
kopiert ausschließlich innerhalb des eigenen Prozesses, ohne Seitenschutz
zu ändern. Erst eine vollständig bestätigte Kopie und ein erneuter Hashgleichstand
liefern `supplied=true`. Die ursprüngliche API-Rückgabe und der
Win32-Fehlerzustand bleiben erhalten. Der zusätzliche Export in Schema 4
enthält Bereichsmetadaten und Ergebnisse, keine Quellpfade oder Quellhashes.

Die Lease bezeichnet die geplante Ladeanforderung. Die Steam-Dateianfrage
selbst enthält diese Ladekennung nicht. Diese begrenzte Zuordnung ersetzt
deshalb noch keine vollständige Engine-Ladetransaktion. Insbesondere wird
ein abweichender Originalpuffer in diesem Schritt nicht ersetzt.

## Geschützter nativer Nachweis

Der private Treiber kopierte ausschließlich den freigegebenen Slot 4 vom
11.11.2026 aus der geprüften Originalsicherung in einen neuen ignorierten
Arbeitsordner. 13 vererbte Lesesperren schützten zwölf persönliche
Save-/Cache-Dateien und diese Kopie. Die zehn nativen Steam-Writer-Sperren
blieben aktiv. Erst ein frischer Katalogeintrag mit exakt dem erlaubten
Zeitwert gestattete einen einzigen Ladevorgang.

Auf RE2 Build 11636119, REFramework d1461375 und TDB 70 wurden zwei
vollständige Originalabschlüsse für den alten Slot beobachtet. Beide
Antwortpuffer bestanden den Vorvergleich; aus der unveränderlichen Kopie
wurden je 2.296.640 Bytes übernommen und danach erneut erfolgreich geprüft.
Es gab keine abgewiesene Replay-Anfrage oder Buchführungsfehler. Acht
unterschiedliche native Zustandssequenzen bestätigten die geladene Szene.

Es wurden keine Bewegungs-, Kampf-, Speicher- oder Cloud-Schreibbefehle
gesendet. Alle zwölf Originaldateien und die private Kopie blieben bytegleich;
es erschien keine neue Save-Datei. Die eigene Instanz ist beendet und die
Original-DLL geprüft wiederhergestellt. Eine erhöhte Nachkontrolle bestätigte
das weiterhin unveränderte installierte Verbindungspaket 4494ef2.
Die [bereinigten Messwerte](validation/private-read-source-2026-11-19.json)
enthalten keine Speicherinhalte, persönlichen Kennungen oder Save-Fingerprints.

## Tests und nächste Aufgabe

Fünf native Guard-/Trace-/Hash-/Quellentests bestehen lokal. Der neue Test
prüft Quellenhash, Dateigröße, Bindungen, Lease-Fristen, unveränderliche
RAM-Quelle trotz späterer Fixture-Änderung, zwei Übernahmen, Duplikate,
abweichende Originaldaten, Seitenschutz und unveränderten Fehlerzustand.
Diese synthetischen Tests schreiben ausschließlich eigene Fixture-Dateien.

Maaviis/Codex untersucht als Nächstes die übrigen Metadaten- und Lesepfade
und definiert eine vollständig private Speichertransaktion samt Fehler- und
Neustartverhalten. Erst danach kommt eine private Schreibumgebung infrage.
Dieser Entwurf führt weiterhin die ursprünglichen Steam-Leseoperationen aus;
er isoliert keine persönlichen Speicherordner und ermöglicht kein gemeinsames
Speichern. Vollständiger Callback-Nachweis, kontenübergreifende Portabilität,
gemeinsame Welt/Kampf/Cutscenes, Rejoin und zwei echte Instanzen bleiben offen.
