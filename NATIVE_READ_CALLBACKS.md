# Tatsächlichen Steam-Leseabschluss nativ bestätigt

Die geschützte Probe vom 19. November 2026 bestätigt für beide vollständigen
Anfragen des freigegebenen alten Slots 4 eine echte Registrierung und eine
echte Zustellung von Callback 1332. Die Callback-Daten stimmen mit Handle,
Offset und angeforderter Größe überein; danach ist die Szene geladen.
Der Original-Steam-Ablauf bleibt bestehen. Dieser Entwurf erzeugt noch
keine eigenen asynchronen Anfragen oder Callbacks.

## Option und Importanbindung

`RE2_COOP_STORAGE_READ_TRACE=1` und `RE2_COOP_READ_CALLBACKS=1` aktivieren
die zusätzliche Diagnose. Ohne diese Option bleiben die Spiel-Imports,
Callback-Klassen und der zusätzliche Export unberührt. Die zehn nativen
Writer-Sperren bleiben aktiv; das installierte Paket bleibt 4494ef2.

Der Beobachter sucht ausschließlich die beiden benannten Delay-Imports
`SteamAPI_RegisterCallResult` und `SteamAPI_UnregisterCallResult` von
`steam_api64.dll` im eigenen laufenden RE2-Modul. Der begrenzte PE-Leser
prüft Windows-x64-Header, Bildgröße, RVA-basierte Deskriptoren, Verzeichnisse,
INT-/IAT-Bereiche, begrenzte Namen und eindeutige Zuordnung. Ungültige,
doppelte oder abgeschnittene Angaben werden abgewiesen. Es wird kein
Code im Spiel oder in den Steam-Exporten gepatcht.

SDK-Exporte müssen aus der geladenen Steam-API-DLL stammen. Ein Importziel
muss bereits dieser Export oder ein ausführbarer spielinterner Zielzeiger
des geprüften Delay-Imports sein. Fremde Modulziele werden abgewiesen.
Beide Importeinträge werden gegen ihren zuvor geprüften Wert ausgetauscht;
Argumente gehen unverändert an die festen aufgelösten SDK-Exporte. Das
funktioniert auch für einen noch nicht aufgelösten Delay-Eintrag, weil die
Steam-DLL bereits geladen und der Spielkontext geprüft ist. Ein vollständiger
Test sämtlicher Delay-Loader-Fehlerfälle ist damit nicht gegeben.

## Callback-Klasse und unabhängige ABI-Prüfung

Nur eine eindeutig bekannte Leseanfrage aus dem bestehenden Trace erlaubt
die Beobachtung des Callback-Objekts. Die Präfixfelder werden begrenzt
gelesen; die Kennung muss 1332 sein. Die drei virtuellen Methoden müssen
anfangs aus dem eigenen Spielmodul stammen. Der öffentliche
`GetCallbackSizeBytes()`-Getter wird zusätzlich rein lesend aufgerufen und
muss 24 Bytes bestätigen. Erst dann werden die beiden Run-Einträge der
zugehörigen Klasse mit unveränderten Weiterleitungen versehen.

Für den geprüften MSVC-x64-ABI gilt:

| Eintrag | Tatsächliche Methode |
|---|---|
| 0 | Run(payload, bool IOFailure, 64-bit call handle) |
| 1 | Run(payload) |
| 2 | GetCallbackSizeBytes() |

Die beiden überladenen Run-Methoden stehen damit anders als in ihrer
Deklarationsreihenfolge. Ein früher Fixture-Entwurf hatte diese Reihenfolge
falsch nachgebildet und der erste reale Versuch erreichte das Titelmenü
nicht. Der unabhängige neue Test ruft jetzt die virtuellen Methoden über die
echten gepinnten
[CCallbackBase-Deklarationen](https://github.com/ValveSoftware/source-sdk-2013/blob/e1f1fd42271805072f052051c26c21caa2c87b04/src/public/steam/steam_api_common.h)
auf. Er prüft Methodeneinträge, Präfixgröße 16, Flags an Offset 8 und Kennung
an Offset 12. Die Hook-Zuordnung und die integrierte Fixture sind entsprechend
korrigiert. CI benötigt dafür die bereits gepinnten Steam-Public-Header;
[SAVE_PROTECTION.md](SAVE_PROTECTION.md) enthält den aktualisierten Build-Aufruf.

Höchstens vier Klassen werden pro Prozess angebunden. Ihre ursprünglichen
Methoden bleiben unveränderlich und erhalten eigene Weiterleitungen; weitere
Klassen werden ausdrücklich gezählt. Callback-Instanzen oder Payload-Zeiger
werden nicht über den jeweiligen Aufruf hinaus gehalten. Beim Run werden
alle benötigten primitiven Daten vor dem Originalaufruf erfasst. Der Originalcode
darf Objekt und Daten freigeben; danach wird beides nicht erneut gelesen.

Bei der Variante mit Handle wird die unabhängige Handle-Übereinstimmung
geprüft. Die Einzelparameter-Variante besitzt keinen Handle-Parameter und
kann nur den Handle aus ihrem Payload zuordnen. Bei IOFailure wird der
Payload nicht gelesen. Originale Argumente und Win32-Fehlerzustände bleiben
erhalten; es wird kein Erfolg erfunden. Ein `returned`-Eintrag besagt, dass
die ursprüngliche void-Methode zurückkehrte, nicht dass allein eine
Registrierung bereits eine Zustellung beweist.

Import- und Klasseneinträge werden mit Eigentumsprüfung zurückgestellt.
Fremde Änderungen werden nicht überschrieben. Feste Originaldelegaten
erlauben späte zwischengespeicherte Aufrufe nach Detach. Der Export
`re2_coop_read_callbacks.json` verwendet Schema 1 mit PID, Startkennung,
App und Build. Er enthält getrennte Gesamt-/Zuordnungszähler und die
letzten 128 zugeordneten Rückkehrereignisse. Fehler, Verdrängung und
Klassenbegrenzung bleiben sichtbar. Native Adressen, Handles, unbekannte
Zeichenketten und Callback-Objektverweise werden nicht exportiert.

## Geschützter Spielnachweis

Die finale Probe verwendete RE2 Build 11636119, REFramework d1461375 und
TDB 70. Sie prüfte erneut exakt Slot 4 vom 11.11.2026. 13 vererbte
Lesesperren schützten zwölf Originaldateien und die geprüfte private Kopie;
die zehn nativen Writer-Sperren blieben aktiv. Der Treiber brachte ausschließlich
sein eigenes, geprüftes RE2-Fenster über das Terminal in den Vordergrund,
ohne Maus- oder Tastaturereignisse. Eine vorherige korrigierte Probe ohne
bestätigten Fokus hatte bereits beide Callback-Daten erfasst, erreichte
aber noch nicht den abgeschlossenen Szenenwechsel.

Ein Import war beim Anbinden noch nicht aufgelöst. Eine einzige Callback-Klasse
wurde erfasst. Insgesamt vier bekannte Leseanfragen wurden registriert und
über die Variante mit IOFailure-/Handle-Parametern zugestellt. Die ersten
beiden betrafen Titeldaten; die beiden folgenden den alten Slot 4.

Für die lokalen Anfragekennungen 3 und 4 bestätigt der jeweilige Callback:
Kennung 1332, Formatgröße 24, IOFailure false, Resultat 1, unabhängige
Handle-Übereinstimmung, Offset null und exakt 2.296.640 Bytes. Beide
Original-Run-Aufrufe kehrten zurück. Ihre vollständigen Leseantworten wurden
weiterhin geprüft aus der identischen privaten Kopie befüllt.

Alle acht Registrierungs-/Zustellereignisse sind erhalten. Keine
Beobachtungs-/Buchführungsfehler, keine Verdrängung oder weitere Klasse.
Unregister und Einzelparameter-Run wurden in der finalen Probe nicht
aufgerufen; ihre Weiterleitung ist nur synthetisch geprüft. Der bisher
überwachte Utils-Pollingpfad blieb weiterhin ungenutzt.

Elf unterschiedliche native Zustandssequenzen und `scene_loaded` bestätigen
die geladene Szene. Es wurden keine Bewegungs-, Kampf-, Save- oder
Cloud-Schreibbefehle gesendet. Alle zwölf Originaldateien und die Kopie
blieben bytegleich, keine neue Save-Datei erschien. Der eigene Prozess
ist beendet und die ursprüngliche DLL geprüft zurückgestellt. Die erhöhte
Nachkontrolle bestätigt die unveränderte installierte Runtime 4494ef2.
Die [bereinigten Messwerte](validation/native-read-callbacks-2026-11-19.json)
enthalten keine Speicherdateien, Save-Fingerprints oder persönlichen Kennungen.

## Tests und nächste Aufgabe

Zehn native Tests bestehen lokal. Neben dem unabhängigen SDK-ABI-Test prüfen
die neuen Fixtures den begrenzten Delay-Import-Leser, fehlerhafte/mehrdeutige
Tabellen, Eigentumswechsel und Seitenschutz sowie die echte Read-/Writer-
Zuordnung mit Registrierungen und beiden Callback-Varianten. Ein Original-
Callback gibt sein Objekt und seinen Payload tatsächlich frei. Parallele
Registrierungen, Ringhistorie, vier getrennte Klassen, Kapazitätsüberschreitung,
fremde Änderungen und späte Aufrufe werden ebenfalls geprüft.

Maaviis/Codex setzt als Nächstes die private asynchrone Lesetransaktion um:
Existenz, Größe und Bytes müssen aus derselben unveränderlichen Generation
stammen; Anfrage, Registrierung, Abbruch, einmalige Zustellung und Abschluss
müssen zusammengehören. Erst danach können die ursprünglichen Leseanfragen
für den geprüften privaten Bereich entfallen. Die jetzige Probe verwendet
weiterhin echte Steam-Anfragen und -Callbacks. Vollständige Speicherisolation,
private Schreibumgebung, kontenübergreifende Portabilität, gemeinsame Welt,
Kampf, Cutscenes, Rejoin und die spätere Zwei-PC-Abnahme bleiben offen.
