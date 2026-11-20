# Asynchrone Steam-Ergebnisse: Pollingpfad eingegrenzt

Der Versuch in diesem Dokument stammt aus dem ursprünglichen Entwurf #114
mit #112. Der [erneute Lauf auf dem integrierten Schutzstand](NATIVE_READ_CALLBACKS.md#integration-auf-dem-gemeinsamen-schutzstand-20-november-2026)
bestätigt beim Laden ebenfalls null Aufrufe über die drei SteamUtils-Methoden
und beobachtet die tatsächlichen Steam-Callbacks.

Die geschützte Einzelinstanz-Probe vom 19. November 2026 lädt den erlaubten
alten Slot 4 erfolgreich, ruft dabei aber keine der drei überwachten
SteamUtils010-Ergebnismethoden auf. Das ist ein negativer Pfadbefund:
Der tatsächliche Abschluss-/Callback-Pfad ist damit noch nicht nachgewiesen.
Die private Ladetransaktion darf diese Methoden deshalb nicht als bereits
bestätigten Ersatz für die Spielanfragen behandeln.

## Optionale Diagnose

Neben `RE2_COOP_STORAGE_READ_TRACE=1` aktiviert
`RE2_COOP_READ_CALL_RESULTS=1` eine zusätzliche rein lesende Weiterleitung.
Sie betrifft ausschließlich die SteamUtils010-Methodentabelle:

| Slot | Methode | Beobachtung bei eindeutig bekannter Leseanfrage |
|---|---|---|
| 11 | IsAPICallCompleted | Originalrückgabe und bei true lesbares Fehlerflag |
| 12 | GetAPICallFailureReason | Vorzeichenbehafteter Original-Fehlercode |
| 13 | GetAPICallResult | Originalrückgabe, Callback-Typ/-Größe, gegebenenfalls Ergebnisfelder |

Methodenreihenfolge und Signaturen stammen aus den gepinnten
[SteamUtils010-Definitionen](https://github.com/ValveSoftware/source-sdk-2013/blob/e1f1fd42271805072f052051c26c21caa2c87b04/src/public/steam/isteamutils.h).
Die Speicherantwort folgt dem öffentlichen
[RemoteStorageFileReadAsyncComplete_t](https://github.com/ValveSoftware/source-sdk-2013/blob/e1f1fd42271805072f052051c26c21caa2c87b04/src/public/steam/isteamremotestorage.h).
Callback 1332 wird nur bei exakt 24 Bytes im geprüften Windows-x64-Layout
gelesen. Feldpositionen und Gesamtgröße sind statisch geprüft.

Die ursprünglichen Empfänger, Argumente, Ausgabepuffer, Rückgaben und
Win32-Fehlerzustände bleiben unverändert. Ausgaben werden erst nach dem
Originalaufruf gelesen. Bei false werden Fehlerflag und Payload nicht
ausgewertet. Ein Fehlerflag muss als einzelnes Byte 0 oder 1 lesbar sein;
andere Darstellungen liefern einen Diagnosefehler. Payload-Felder werden
nur bei erfolgreicher Originalrückgabe, lesbarem false-Fehlerflag und
passendem Callback-Typ/-Format gelesen. Die Diagnose führt keine eigenen
Leseanfragen aus und konsumiert keine zusätzlichen Ergebnisse.

Der vorhandene Lese-Trace liefert dafür eine neue rein lesende Handle-Suche.
SteamUtils übergibt keinen RemoteStorage-Empfänger. Daher ist eine Zuordnung
nur zulässig, wenn über alle gehaltenen Empfänger hinweg genau eine bekannte
Anfrage zu diesem Handle existiert. Mehrdeutige, wiederverwendete, unbekannte,
nicht gehaltene oder ungültige Handles erhalten kein Ereignis. Erfolgreich
abgeschlossene Schlüssel bleiben erhalten und kennzeichnen späte Abfragen
als completed. Es werden keine Handles oder nativen Objektadressen exportiert.

Der zusätzliche Bericht `re2_coop_read_call_results.json` verwendet Schema 1
mit PID, Startkennung, App, Build und geprüftem Utils-Kontext. Originalzähler
und zugeordnete Zähler bleiben getrennt. Die letzten 128 zugeordneten
Abschlüsse werden geordnet gehalten; Verdrängung und Fehler sind sichtbar.
Payloads liefern nur primitive Felder sowie Vergleichsergebnisse für
Handle, Offset und angeforderte Größe. Rohberichte verbleiben lokal.
Ohne Option bleiben die drei Methoden und der zusätzliche Export unberührt.
Die zehn nativen Writer-Sperren bleiben aktiv.

## Geschützter negativer Laufzeitbefund

Die Probe nutzte RE2 Build 11636119, REFramework d1461375 und TDB 70.
Sie bestätigte vor dem einzelnen Load erneut exakt Slot 4 vom 11.11.2026.
13 vererbte Lesesperren schützten zwölf persönliche Originaldateien und
eine geprüfte private Kopie. Die native Schreibsperre blieb aktiv.

Die zusätzlichen Utils-Einträge waren erfolgreich angebunden, ihre
Steam-Modulherkunft und der Schnittstellenkontext geprüft. Vor und nach dem
Load bleiben alle drei Methodenzähler null. Entsprechend gibt es keine
zugeordneten Ergebnisereignisse. Es gab keine Beobachtungs- oder
Buchführungsfehler. Das bestätigt die Anbindung ohne einen positiven
Laufzeitnachweis für die drei Weiterleitungen zu liefern.

Gleichzeitig bestätigten die bisherigen Leser die beiden vollständigen
Slot-Antworten sowie ihre passenden Existenz- und Größenangaben. Die zwei
identischen Antworten aus der privaten Kopie wurden weiterhin geprüft
befüllt. 17 unterschiedliche native Zustandssequenzen bestätigen die
geladene Szene. Es gab keine Bewegungs-, Kampf-, Save- oder Cloud-Schreibbefehle.
Alle zwölf Originaldateien und die Kopie blieben bytegleich; keine neue
Save-Datei erschien. Die eigene Instanz ist geschlossen und die ursprüngliche
DLL geprüft zurückgestellt. Die installierte Runtime bleibt 4494ef2.
Die [bereinigte Evidenz](validation/native-read-call-results-2026-11-19.json)
kennzeichnet den fehlenden nativen Ergebnisnachweis ausdrücklich.

Eine rein lesende Binärprüfung findet in der verwendeten EXE die
Schnittstellenkennung SteamUtils010 sowie Imports für
SteamAPI_RegisterCallResult, SteamAPI_UnregisterCallResult und
SteamAPI_RunCallbacks. Die Importtabelle enthält auch verzögerte Imports.
Das beweist noch keine tatsächlich erfolgte Registrierung oder Zustellung.

## Tests und nächste konkrete Aufgabe

Sieben native Tests bestehen lokal. Ergänzt wurden die konservative
Handle-Suche über Empfänger hinweg sowie ein integrierter Fixture-Test
mit den echten Read-/Writer-Beobachtern und einer synthetischen Utils-Tabelle.
Er prüft vollständige 64-Bit-Handles, ausstehende/fehlgeschlagene Ergebnisse,
unveränderte Ausgabepuffer und Fehlerzustände, Callback-Typ/-Größe,
abweichende Payloads, ungültige Bool-/Pointerbeobachtungen, Parallelität,
Ringverdrängung, Integrität, späte Aufrufe und eigentumserhaltenden Detach.
Die synthetischen Payloads sind ausdrücklich keine nativen Spielbelege.

Maaviis/Codex prüft als Nächstes den tatsächlichen Registrierungs- und
Callback-Ablauf an den Spiel-Imports, einschließlich verzögerter Auflösung.
Erst ein an die bekannte Leseanfrage gebundener realer Callback-Nachweis
rechtfertigt dessen Übernahme in eine private asynchrone Transaktion.
Wiederholte identische Pollingproben würden diesen fehlenden Pfad nicht
klären. Eigene Anfragen, Callback-Erzeugung, private Schreibumgebung,
vollständige Speicherisolation, kontenübergreifende Portabilität,
gemeinsame Welt/Kampf/Cutscenes, Rejoin und zwei echte Instanzen bleiben offen.
