# Asynchrone Leseziele und ihre Abschlüsse zuordnen

Die [zusätzliche lokale Inhaltsdiagnose](NATIVE_BUFFER_DIGESTS.md) erweitert
den Export inzwischen auf Schema 3. Die folgende native Zuordnungsmessung
bezieht sich auf die vorausgehende Schema-2-Fassung ohne Puffer-Fingerprints.

Der freigegebene alte Kampagnenslot wird im gemessenen RE2-Build zweimal
über `./win64_save/data004Slot.bin` gelesen. Beide nativen
`FileReadAsyncComplete`-Aufrufe melden Erfolg und gehören jeweils zu einer
Anforderung über 2.296.640 Bytes ab Offset null. Das ist eine konkrete
Zuordnung der Leseaufrufe; eine private Speicherumleitung oder ein
gemeinsamer Koop-Speicherzustand ist damit noch nicht umgesetzt.

## Begrenzte Metadaten neben den Originalaufrufen

Die opt-in-Beobachtung aus [NATIVE_STORAGE_READS.md](NATIVE_STORAGE_READS.md)
erweitert ihren lokalen Export auf Schema 2. Ohne
`RE2_COOP_STORAGE_READ_TRACE=1` werden weiterhin keine Leseeinträge ersetzt.
Die zehn Writer-Sperren, deren Schema-1-Status und die bestehende
Ladefreigabe bleiben unverändert.

Die Diagnose erkennt ausschließlich 23 ausdrücklich aufgelistete
RE2-Dateischlüssel: `./win64_save/data00-1.bin`, `./win64_save/data000.bin`
und `./win64_save/data001Slot.bin` bis `data021Slot.bin`. Der führende
`./`-Teil gehört zum tatsächlich gemessenen API-Schlüssel. Vergleich und
Export verwenden die exakten Bytes dieser festen Liste. Es gibt keine
Normalisierung von Großschreibung, Separatoren, absoluten Pfaden oder
zusätzlichen Punktsegmenten. Ein unbekannter Name bleibt `file=null`.

Ein kurzer Name wird dazu mit höchstens 64 einzeln begrenzten
`ReadProcessMemory`-Leseschritten aus dem eigenen Prozess geprüft. Ein
ungültiger Zeiger oder ein fehlendes Ende meldet einen Klassifikationsfehler,
ohne den Originalaufruf zu ersetzen. Die temporäre Kopie wird verworfen und
genullt. Exportiert werden nur bekannte Namen aus der festen Liste, keine
beliebigen Eingaben, lokalen Kontopfade oder Pufferinhalte.

Die Aufrufe werden weiterhin genau einmal mit unveränderten Argumenten,
Datenfluss und Rückgabewerten weitergeleitet. Die Diagnose erhält auch
den Win32-Fehlerzustand vor dem Originalaufruf beziehungsweise danach.
Beim Aufruf des Originals wird kein Metadaten-Lock gehalten. Ereignisse
bezeichnen die Rückkehr aus der nativen Methode, keine zusätzlich
beobachtete Zustellung eines Steam-Callbacks.

## Anfrageidentität und Grenzen der Historie

Nach `FileReadAsync` speichert der Beobachter nur eine lokale laufende
Anfragekennung, den bekannten Dateischlüssel oder Unbekannt, Offset,
angeforderte Größe und intern das Paar aus Interface-Empfänger und
64-Bit-Steam-Handle. Native Handles und Empfängeradressen werden nicht
exportiert. Ein Abschluss wird nur demselben intern erfassten Paar
zugeordnet. Der originale boolesche Rückgabewert bleibt sichtbar.

Ein fehlgeschlagener Abschluss beendet die Beobachtung nicht als Erfolg;
ein späterer erneuter Abschluss kann getrennt erfasst werden. Erfolgreich
abgeschlossene Schlüssel bleiben als bereits verwendete Schlüssel erhalten.
Ein doppelter Abschluss wird deshalb nicht erneut gutgeschrieben. Eine
erneute Verwendung desselben Schlüssels macht ihn dauerhaft mehrdeutig;
weitere Abschlüsse bekommen dann keine erfundene Dateizuordnung.

Pro Prozesslauf werden höchstens 64 solche Schlüssel behalten, einschließlich
bereits abgeschlossener Schlüssel. Weitere Anfragen laufen unverändert durch
die echte API, erhalten aber einen expliziten Überlaufvermerk. Die letzten
64 Ereignisse werden mit steigender Sequenz und einem Verlustzähler
exportiert. Eine volle Historie wird nicht als vollständiges Protokoll
ausgegeben. Ein Abschluss vor der Erfassung seiner Anfrage bleibt ebenfalls
nicht zugeordnet; die Diagnose rekonstruiert keine vermeintliche Verbindung.

Der Export enthält neben den bisherigen Aufrufzählern:

- `trace_available`, `classification_errors` und begrenzte Ledger-Zähler;
- `targets` mit bekannten Dateischlüsseln, Anfragen, Bereichen und
  zugeordneten erfolgreichen/fehlgeschlagenen Abschlussaufrufen;
- `events` mit lokaler Anfragekennung, Phase, Bereich und Originalergebnis;
- Sequenz und `discarded_events` sowie Anzahl ausstehender, mehrdeutiger
  und bereits behaltener Schlüssel.

`successful_completion_bytes` summiert die übergebenen Abschlussgrößen bei
originalem Ergebnis `true`. Dieser Wert ist kein gelesener Pufferprüfwert.
Die Diagnose prüft keine entschlüsselten Inhalte oder Vollständigkeit aller
Engine-Lesewege. Zwischen globalen Aufrufzählern und der geschützten
Metadatenprobe kann ein Aufruf noch laufen. Prozess, Startkennung, Alter,
Load und Steam-Sitzung muss ein künftiger Verbraucher zusätzlich binden.
Überläufe, verlorene Ereignisse, unbekannte Ziele und nicht zugeordnete
Abschlüsse dürfen keine Freigabe für einen unbewiesenen Speicherzustand geben.

## Geschützter nativer Nachweis vom 18. November 2026

Getestet wurde RE2 Build 11636119, REFramework d1461375, TDB 70 auf der
installierten geschützten Runtime 4494ef2. Nur die Guard-DLL wurde für den
eigenen Prozess temporär ersetzt. Vererbte Dateisperren und die zehn nativen
Writer-Sperren blieben aktiv. Geladen wurde ausschließlich der freigegebene
Slot 4 vom 11.11.2026. Der Treiber hatte keine Bewegungs-, Kampf-, Save-
oder Cloud-Schreibbefehle.

| Phase | Exakter API-Dateischlüssel | Anforderung und Abschluss |
|---|---|---|
| Vor dem Kampagnenload | `./win64_save/data021Slot.bin` | Einmal 1.124 Bytes, Offset 0, zugeordneter Abschluss `true` |
| Vor dem Kampagnenload | `./win64_save/data00-1.bin` | Einmal 7.564 Bytes, Offset 0, zugeordneter Abschluss `true` |
| Freigegebener Kampagnenload | `./win64_save/data004Slot.bin` | Zweimal je 2.296.640 Bytes, Offset 0, zwei verschiedene lokale Anfragekennungen und jeweils Abschluss `true` |

Die zwei Kampagnenanforderungen erscheinen nach der unmittelbar vor dem
Load erfassten Ereignissequenz. Es gab keine Klassifikationsfehler,
Mehrdeutigkeiten, verlorenen Ereignisse, übergelaufenen oder verbleibenden
Anfragen. 19 verschiedene native Zustandssequenzen bestätigten das geladene
Spiel. Ein erlaubter Load, keine Lua-Speicheranforderung und alle zehn
nativen Writerzähler null wurden erfasst. Alle zwölf Save-/Cache-Dateien
blieben bytegleich; es entstand keine neue Save-Datei.

Die eigene Instanz wurde geschlossen und die Original-DLL anschließend
SHA-256-geprüft wiederhergestellt. Eine erhöhte Abschlussprüfung bestätigte
keinen laufenden RE2-Prozess und die unveränderte installierte Runtime.
Eine zuvor nötige reine Namensdiagnose blieb vollständig lokal; sie gehört
weder zum öffentlichen Quellcode noch zum Nutzerpaket.

Die [bereinigten Messwerte](validation/native-storage-targets-2026-11-18.json)
enthalten keine privaten Kontopfade, Save-GUIDs oder Steam-Handles. Der
Rohbericht bleibt lokal. Die Messung bestätigt die API-Schlüssel, Bereiche
und zugeordneten Originalergebnisse. Sie bestätigt noch keinen Vergleich
der gelesenen Puffer mit einer privaten Testkopie.

## Prüfungen und nächster Schritt

Die nativen Tests decken unter anderem exakte Dateischlüssel,
Namensgrenzen vor einer nicht lesbaren Speicherseite, ungültige Zeiger,
unveränderte Fehlerzustände, getrennte Empfänger, 64-Bit-Handles,
Fehlversuche/erneute Abschlüsse, Teilbereiche, doppelte Abschlüsse,
Handle-Wiederverwendung, Kapazitätsgrenzen, parallele Aufrufe und eine
verfrüht eintreffende Abschlussbeobachtung ab. Die drei Guard-/Trace-Tests
bestehen lokal; es werden dabei keine echten Save-Schreibpfade ausgeführt.

Als Nächstes ist der Inhalt der zugeordneten Leseantwort mit einer
geprüften privaten Kopie des freigegebenen alten Slots zu vergleichen.
Erst danach folgt ein abgegrenzter privater Lesepfad. Eine spätere isolierte
Schreibumgebung muss zusätzlich die asynchronen Steam-Ergebnisse und deren
Zustellung korrekt abbilden. Private Save-Schreibvorgänge, normale
Kampffortsetzung, gemeinsame Checkpoints, Rejoin und zwei echte Steam-Konten
bleiben gesonderte offene Abnahmen.
