# Dateiabfragen vor den nativen Leseantworten

Der Versuch in diesem Dokument stammt aus dem ursprünglichen Entwurf #113
mit #112. Der [erneute Lauf auf dem integrierten Schutzstand](NATIVE_READ_CALLBACKS.md#integration-auf-dem-gemeinsamen-schutzstand-20-november-2026)
bestätigt die Dateiabfragen und die unveränderte Weiterleitung auf einer
geschützten lokalen Kopie.

Die geschützte Probe vom 19. November 2026 bestätigt beim Laden des alten
Slots 4 zwei zusätzliche Aufrufe von `FileExists` und `GetFileSize`.
Beide Existenzabfragen liefern true, beide Größenabfragen 2.296.640 Bytes.
Eine private Speicherumgebung muss diese Angaben mit ihren tatsächlichen
Antwortdaten konsistent halten. Die Diagnose verändert keine dieser Angaben.

## Optionale Weiterleitung

`RE2_COOP_STORAGE_METADATA=1` aktiviert einen eigenen Beobachter. Ohne diese
Option bleiben alle zehn Metadatenmethoden unberührt und es wird kein
Metadatenbericht geschrieben. Die Option ist unabhängig vom bestehenden
Lese-Trace und von dessen privatem Antwort-Replay. Die native Schreibsperre
mit zehn Writer-Methoden bleibt bestehen.

Die Methodenzuordnung folgt der veröffentlichten
[RemoteStorage014-Schnittstelle im Steamworks SDK 1.51](https://github.com/ValveSoftware/Proton/blob/proton_9.0/lsteamclient/steamworks_sdk_151/isteamremotestorage.h).
Die zusätzlichen Einträge müssen im laufenden Prozess ebenfalls aus den
geprüften Steam-Modulen stammen. Die Modifikation betrifft ausschließlich
die tatsächliche v014-Methodentabelle; sie patcht keine aliasten Flat-Exporte.

| Slot | Rein lesende Methode | Beobachtete Daten |
|---|---|---|
| 13 | FileExists | Bool-Rückgabe pro bekanntem Ziel |
| 14 | FilePersisted | Bool-Rückgabe pro bekanntem Ziel |
| 15 | GetFileSize | Vorzeichenbehaftete 32-Bit-Größe |
| 16 | GetFileTimestamp | Vorzeichenbehafteter 64-Bit-Zeitwert |
| 17 | GetSyncPlatforms | Ungekürzte 32-Bit-Plattformbits |
| 18 | GetFileCount | Vorzeichenbehaftete Anzahl |
| 19 | GetFileNameAndSize | Index, bekannte Zielklasse, zurückgegebene Größe |
| 20 | GetQuota | Bool-Rückgabe und zwei ungekürzte 64-Bit-Ausgaben |
| 21 | IsCloudEnabledForAccount | Bool-Rückgabe |
| 22 | IsCloudEnabledForApp | Bool-Rückgabe |

Die originale Empfängeradresse, sämtliche Argumente, Ausgabepuffer,
Rückgabewerte und Win32-Fehlerzustände bleiben erhalten. Beobachtungen lesen
Ausgaben erst nach der Originalrückkehr und nur bei dafür gültigem Ergebnis.
Nicht lesbare Ausgaben liefern einen Diagnosefehler und verändern die
Originalrückgabe nicht. Die Beobachtung führt keine eigenen Datei- oder
Netzwerkoperationen aus. Ihre Metadaten-Locks werden erst nach der Rückkehr
aus dem ursprünglichen Steam-Aufruf gehalten.

Native Namen werden begrenzt und speicherseitensicher klassifiziert. Nur die
23 vorhandenen bekannten Save-Schlüssel werden gespeichert; andere Namen
erscheinen ausschließlich als unknown. Für diese feste Zielklasse werden
Groß-/Kleinschreibung und ein optionales führendes `./` berücksichtigt, weil
Steam Dateinamen ohne Beachtung der Großschreibung behandelt und bei der
Aufzählung kleinschreibt. Argumente werden dadurch nicht umgeschrieben;
Traversierung oder beliebige Pfadnormalisierung findet nicht statt.

Der lokale Export `re2_coop_storage_metadata.json` verwendet Schema 1 und
bindet sich an PID, Startkennung, App und Build. Er enthält Methodenzähler,
aggregierte Zielzähler und die letzten 128 abgeschlossenen Beobachtungen in
Reihenfolge. Verdrängte Ereignisse sowie Beobachtungs-/Buchführungsfehler
werden ausdrücklich gezählt. Die Aggregate bleiben über eine Verdrängung
hinaus erhalten. Zähler beim Eintritt und abgeschlossene Ereignisse sind bei
laufenden parallelen Aufrufen nicht derselbe atomare Zeitpunkt. Es werden
keine Handles, Adressen oder unbekannten nativen Zeichenketten exportiert.
Rohberichte mit persönlichen Metadaten verbleiben lokal.

## Geschützter Laufzeittest

Die Probe behielt die geprüfte Quelle aus #112 bei: eine private unveränderte
Kopie ausschließlich des freigegebenen alten Slots 4 vom 11.11.2026.
13 vererbte Lesesperren schützten zwölf Originaldateien und diese Kopie;
zehn native Writer-Sperren waren aktiv. Nur ein erneuter frischer Katalogabgleich
mit dem freigegebenen Zeitwert gestattete den einzelnen Ladevorgang.

Am Titelbild wurden je zwei Existenz- und Größenabfragen erfasst. Sie
betrafen `data021Slot.bin` und `data00-1.bin`. Nach der Ladeauswahl kamen je
zwei Abfragen für `data004Slot.bin` hinzu. Alle acht Ereignisse sind erhalten;
es gab keine unbekannten Ziele, Beobachtungsfehler oder Verdrängung.
Die übrigen acht Methoden wurden in diesem Ablauf nicht aufgerufen und sind
daher nur synthetisch auf ihre Weiterleitung geprüft.

Die beiden ursprünglichen asynchronen Slot-Antworten wurden weiterhin
erfolgreich mit der geprüften Quelle verglichen und aus ihr befüllt. 13
unterschiedliche native Zustandssequenzen bestätigen die geladene Szene.
Es gab keine Bewegungs-, Kampf-, Speicher- oder Cloud-Schreibbefehle.
Alle zwölf Originaldateien und die private Kopie blieben bytegleich; keine
neue Save-Datei erschien. Die eigene Instanz wurde beendet und die Original-DLL
geprüft zurückgestellt. Eine erhöhte Nachkontrolle bestätigt weiterhin die
installierte Runtime 4494ef2. Die
[bereinigten Messwerte](validation/native-storage-metadata-2026-11-19.json)
veröffentlichen ausschließlich diesen Prüfumfang.

## Tests und nächster Schritt

Sechs native Guard-/Read-/Hash-/Quellen-/Metadatentests bestehen lokal.
Der neue Test prüft alle zehn Signaturen, negative Werte, vollständige
64-Bit-Werte, unveränderte Rückgabezeiger und Fehlerzustände, ungültige
Beobachtungspointer, parallele Aufrufe und Ringverdrängung. Separate Tabellen,
späte Aufrufe nach Detach, fremde Tabellenänderungen, Seitenschutz sowie die
unveränderte Schreibsperre und Cloud-Setterposition werden geprüft.

Maaviis/Codex bearbeitet als Nächstes die private asynchrone Ladetransaktion:
Existenz, Größe und Inhalt müssen aus derselben unveränderlichen Generation
stammen. Anfrage, echtes Abschlussverhalten, Fehler, Abbruch und Neustart
brauchen eine gemeinsame Zustandsmaschine, bevor Original-Leseaufrufe entfallen
oder private Schreiboperationen freigegeben werden. Ein passender Antwortpuffer
allein beweist keine vollständige Isolation. Weitere Engine-Wege, vollständige
Steam-Callback-Abnahme, kontenübergreifende Portabilität, gemeinsame Welt,
Kampf, Cutscenes, Rejoin und zwei echte Instanzen bleiben offen.
