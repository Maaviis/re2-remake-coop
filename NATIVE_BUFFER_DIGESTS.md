# Native Leseantwort mit einer privaten alten Save-Kopie vergleichen

Die beiden vollständig angeforderten Leseantworten für den freigegebenen
alten Slot 4 stimmen in der nativen Probe vom 18. November 2026 per SHA-256
mit einer geprüften privaten Kopie überein. Die Antwortpuffer wurden dabei
nur gelesen. Das bestätigt ihren beobachteten Inhalt, ohne bereits einen
privaten Lesepfad oder eine Speicherumleitung einzurichten.

## Zusätzliche ausdrückliche Option

Neben `RE2_COOP_STORAGE_READ_TRACE=1` verlangt die Inhaltsdiagnose
`RE2_COOP_STORAGE_READ_DIGEST=1`. Ohne die zusätzliche Option werden keine
Antwortpuffer gelesen oder gehasht. Die Konfiguration wird vor der
einmaligen Anbindung der nativen Leseweiterleitungen festgelegt.
Die zehn Writer-Sperren und ihr Schema-1-Freigabestatus bleiben unverändert.
Das installierte Nutzerpaket wurde nicht durch diese Fassung ersetzt.

Der Trace liefert nach der Rückkehr aus dem ursprünglichen
`FileReadAsyncComplete` eine Kopie seiner zugeordneten Metadaten:
bekannter Dateischlüssel, lokale Anfragekennung, Abschluss-Ereignissequenz,
Offset, angeforderte und übergebene Abschlussgröße sowie Originalergebnis.
Nur eindeutig zugeordnete erfolgreiche Abschlüsse bekannter Ziele innerhalb
der Größenbegrenzung kommen für einen Fingerprint infrage. Mehrdeutige,
unbekannte, fehlgeschlagene oder unpassende Beobachtungen bleiben ausgenommen.

Der Hasher liest ausschließlich den übergebenen Antwortbereich aus dem
eigenen Prozess. Er verwendet höchstens 64 KiB große private Leseblöcke und
begrenzt Bereiche auf 8 MiB. Ungültige, überlaufende oder nicht lesbare
Bereiche liefern einen Fehler. Die temporären Daten und der Hashobjektspeicher
werden genullt; es bleiben keine Antwortpuffer oder native Objektverweise
im Diagnoseprotokoll erhalten. SHA-256 wird über die dokumentierten
[Windows-CNG-Hashfunktionen](https://learn.microsoft.com/en-us/windows/win32/seccng/creating-a-hash-with-cng)
berechnet. Die Algorithmus-/Hashhandles werden wieder freigegeben.

Die Reservierung eines begrenzten Ergebnisplatzes erfolgt vor der Berechnung,
die Berechnung selbst ohne gehaltenen Metadaten-Lock. Bis zu ihrem Abschluss
bleibt `in_progress=true`. Höchstens 64 Anfragen erhalten einen Fingerprint;
Duplikate werden nicht erneut angenommen. Überläufe und Buchführungsfehler
bleiben sichtbar. Ein Snapshot enthält Kopien. Die Originalaufrufe,
Rückgabewerte, Pufferinhalte und Win32-Fehlerzustände bleiben erhalten.

## Lokaler Export und Prüfumfang

`re2_coop_storage_reads.json` verwendet jetzt Schema 3. Die bisherige
Ziel-/Abschlusszuordnung bleibt enthalten. Das zusätzliche Objekt
`buffer_digests` meldet Aktivierung, Verfügbarkeit, Kapazität, Fehler und
begrenzte Ergebnisse mit Anfragekennung, Abschlusssequenz, Datei, Bereich,
Fortschritt und gegebenenfalls SHA-256.

Diese Fingerprints verbleiben im lokalen Diagnosebericht. Save-Kopien,
Dateipfade und Save-Fingerprints gehören nicht in öffentliche Testdaten.
Der öffentliche Nachweis enthält ausschließlich die Vergleichsergebnisse
und Bereichsmetadaten. Ein Hashbericht ist keine gemeinsame Spielfreigabe;
Prozess, Startkennung, Load und Steam-Sitzung müssen zusätzlich gebunden
werden. Weder die Vollständigkeit aller Engine-Lesewege noch die korrekte
Zustellung aller Steam-Callbacks wird damit bewiesen.

## Geschützter nativer Vergleich

Vor dem eigenen Spielstart kopierte der private Treiber ausschließlich
`data004Slot.bin` aus der SHA-256-geprüften Originalsicherung in ein neues,
privates Verzeichnis unter dem ignorierten Arbeitsbereich. Hash und Größe
der Kopie mussten der Originalsicherung entsprechen. Danach wurden zwölf
persönliche Save-/Cache-Dateien und diese Kopie gemeinsam mit insgesamt
13 Lesesperren in den direkt gestarteten Spielprozess vererbt.

Eine temporäre Guard-DLL führte die Beobachtung auf RE2 Build 11636119,
REFramework d1461375 und TDB 70 aus. Der laufende Save-Katalog musste
erneut exakt Slot 4 vom 11.11.2026 bestätigen. Nur dieser Slot wurde einmal
geladen. Es gab keine Bewegungs-, Kampf-, Save- oder Cloud-Schreibbefehle.

Zwei getrennte Anfragen für `./win64_save/data004Slot.bin` verlangten je
2.296.640 Bytes ab Offset null. Beide zugeordneten Abschlussaufrufe lieferten
`true`; beide nativen Puffer-Fingerprints entsprachen der privaten Kopie und
der geprüften Originalsicherung. Die Kopie blieb über den Versuch hinweg
unverändert. Zusätzlich wurden zwei erfolgreich zugeordnete Titelantworten
erfasst; deren Inhalte werden hier nicht veröffentlicht.

Zehn unterschiedliche native Zustandssequenzen bestätigten das geladene
Spiel. Die Diagnose meldete keine Fingerprintfehler. Alle zehn nativen
Writerzähler und die gezählten Lua-Speicheranforderungen blieben null.
Alle zwölf Originaldateien blieben bytegleich, es erschien keine neue
Save-Datei. Der eigene Prozess wurde geschlossen und die Original-DLL
anschließend geprüft zurückgestellt. Eine erhöhte Nachkontrolle bestätigte
keinen laufenden RE2-Prozess und die unveränderte installierte Runtime 4494ef2.

Die [bereinigten Messwerte](validation/native-buffer-digests-2026-11-18.json)
halten Vergleich, Grenzen und Rückbau fest. Private Kopie und Rohbericht
bleiben lokal; sie sind keine Distributionsbestandteile.

## Tests und nächster Schritt

Die nativen Tests prüfen bekannte SHA-256-Vektoren, leere und ausgewählte
Bereiche, mehrere Leseblöcke, ungültige/überlaufende Größen, nicht lesbare
Speicherseiten, unveränderte Quelldaten und Fehlerzustände sowie Anfragebindung,
Duplikate, gleichzeitige Berechnungen und feste Kapazitätsgrenzen. Alle vier
Guard-/Trace-/Hash-CTestfälle bestehen lokal. Die synthetischen Tests führen
keine echten Save-Schreiboperationen aus.

Der nächste Schritt ist ein abgegrenzter privater Lesepfad mit nachgewiesener
Quelle und unverändert korrektem asynchronem Ablauf. In dieser Probe liefert
weiterhin die originale Steam-Schnittstelle die Spielantwort; die private
Kopie dient nur dem unabhängigen Vergleich. Dass das Spiel eine Antwort aus
der Kopie konsumiert, ist noch nicht gezeigt. Private Schreibumgebung,
kontenübergreifende Portabilität, gemeinsame Kampagne, Rejoin und zwei echte
Steam-Konten bleiben offen.
