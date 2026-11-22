# Nachrichtenschema für RE2-Koop, Entwurf v1

Das Schema beschreibt die Nachrichten zwischen Spieladapter, Host und Replik.
`v1.py` ist die ausführbare Referenz für die Strukturprüfung. Die
[Testvektoren](v1-examples.json) enthalten eine Spielerpose, eine Tür, ein
Kampagnenskript, eine Zwischensequenz sowie Snapshots vor und nach den Ereignissen.

## Nachrichten

Eine Nachricht ist genau ein UTF-8-JSON-Objekt. `version` ist die Ganzzahl `1`.
Doppelte Objektschlüssel und nicht endliche Zahlen werden verworfen.
Ganzzahlen in Nachrichten liegen zwischen `-(2^53 - 1)` und `2^53 - 1`, damit
auch Leser mit IEEE-754-Binär64 alle zulässigen Ganzzahlen exakt darstellen
können. Die folgende Tabelle listet alle zulässigen Felder neben `version` und `type`.

| `type` | Richtung | Felder |
| --- | --- | --- |
| `hello` | Host ↔ Gast | Gast kann `heartbeat: true` ergänzen |
| `ping` | Gast → Host | `nonce`, positive Ganzzahl |
| `pong` | Host → Gast | dieselbe `nonce` wie im `ping` |
| `propose` | Beobachter → Host | `kind`, `target`, `value` |
| `event` | Host → Replik | `data` mit `kind`, `target`, `value`, `session_id`, `sequence` und `digest` |
| `snapshot` | Host → Replik | `data` mit `state`, `session_id`, `sequence` und `digest` |
| `error` | Host → Absender | `message` als nicht leerer Text |

`kind` ist einer der folgenden Werte. Die Tabelle nennt die zugehörige
Zustandstabelle im Snapshot.

| Kategorie | Ereignis → Snapshot-Feld |
| --- | --- |
| Spieler und Kampf | `player` → `players`, `action` → `actions`, `damage` → `damage`, `enemy` → `enemies` |
| Welt | `door` → `doors`, `puzzle` → `puzzles`, `item` → `items`, `inventory` → `inventories` |
| Kampagne | `flag` → `flags`, `script` → `scripts`, `cutscene` → `cutscene` |

`target` ist eine nicht leere Objekt-ID als String. Bei `cutscene` ist `target`
`null`, weil der Zustand nur eine aktive Zwischensequenz pro Sitzung führt.
`value` ist ein JSON-Wert. Die für diese Version kompatiblen Spielwerte sind in
den Testvektoren sichtbar. Weitere Felder und Validierungen pro Spielereignis
werden mit der jeweiligen Engine-Anbindung festgelegt.

Ein Snapshot enthält alle elf Felder unter `state`. Mit Ausnahme von `cutscene`
ist jedes Feld ein Objekt, dessen Schlüssel die Objekt-IDs sind. Leere Tabellen
werden als `{}` geschrieben. `cutscene` enthält den aktuellen JSON-Wert oder
`null`. Eine `session_id` ist ein nicht leerer, vom Host vergebener String.
Sequenzen sind Ganzzahlen bis `2^53 - 1`. Der initiale Snapshot darf Sequenz `0`
haben. Das erste Ereignis einer Sitzung hat Sequenz `1`.

## Autorität und Wiederherstellung

- Nur der Host vergibt `session_id` und `sequence` für verbindliche Änderungen.
  Der Host validiert die Rolle des Absenders und die Spielaktion vor der
  Übernahme. Der Strukturtest allein belegt keine Berechtigung.
- `digest` ist der kleingeschriebene hexadezimale SHA-256-Prüfwert des vollständigen
  Zustands nach dem Ereignis bzw. im Snapshot. Für diesen Entwurf ist
  `sync_model.state_digest` die Referenz. Die Eingabe ist UTF-8 ohne BOM,
  Objektschlüssel sind rekursiv sortiert, es gibt keine optionalen Leerzeichen,
  und Nicht-ASCII-Zeichen werden direkt geschrieben. Andere Implementierungen
  müssen die kanonische Zahlendarstellung der Referenz reproduzieren. Bei
  Prüfsummen sind `1` und `1.0` verschiedene Werte. Gleitkommazahlen behalten
  das Vorzeichen von `-0.0`. Der Vektor `canonical_reconnect_state_utf8` liefert
  die exakten UTF-8-Eingabebytes, einschließlich `1e-07`. Der Codec prüft die
  Form des Prüfsummenfelds. `Replica.apply` und `Replica.restore` prüfen den
  tatsächlichen Zustandswert.
- Eine Replik übernimmt zuerst einen Snapshot und dann Ereignisse derselben
  Sitzung in aufsteigender Reihenfolge. Bereits übernommene Sequenzen werden
  ignoriert. Eine Lücke oder ein Prüfsummenfehler erfordert einen neueren oder
  gleich aktuellen Host-Snapshot, bevor weitere Ereignisse übernommen werden.
- Der Engine-Adapter verwendet die zwischen beiden Instanzen vereinbarten
  Objekt-IDs. Speicheradressen und lokal erzeugte Objektreferenzen dienen nur
  zur Zuordnung im eigenen Prozess. Beim Anwenden von Host-Ereignissen hält
  der Adapter deren Herkunft fest, damit beobachtete Folgeänderungen nicht
  erneut als lokale Vorschläge an den Host gehen.

## Migration des Loopback-Prototyps

Der Loopback-CLI verwendet standardmäßig den unversionierten Modus 0. Für
einen v1-Test starten Host und Gast jeweils mit `--protocol-version 1`.

~~~sh
python wire.py host --port 45678 --protocol-version 1
python wire.py client --port 45678 --protocol-version 1
~~~

Der Host sendet zuerst `{"version":1,"type":"hello"}`. Der Gast prüft die
Version und antwortet mit derselben Nachricht. Erst dann sendet der Host einen
Snapshot und registriert den Gast für Ereignisse. Bei einer unpassenden
Version oder einer anderen ersten Nachricht bricht die Verbindung ab. Ein
Host-Handshake endet auch, wenn ein Gast fünf Sekunden lang keine Daten
liefert. Der Versionsabgleich prüft ausschließlich die Formatkompatibilität.

Mit `--listen --events 0` wartet der Gast nach dem Snapshot auch während
längerer Ruhephasen auf Ereignisse. Bei regulärem Verbindungsende gibt er
den zuletzt übernommenen Zustand aus.

Der v1-Diagnosegast öffnet nach EOF, einem Verbindungsfehler, einem
Sequenzsprung oder einem falschen Ereignisdigest eine neue Verbindung,
solange Wiederverbindungsversuche übrig sind. Die Replik behält ihre
Sitzungskennung und zuletzt bestätigte Sequenz. Ein gleich aktueller Snapshot
muss denselben Digest haben. Ein neuerer Snapshot muss zur selben Sitzung
gehören und seinen eigenen Digest bestehen. Vollständige ungültige Frames
oder abgelehnte Snapshots beenden den Lauf.

Mit `guest_pose.py --host-heartbeat` fordert der Gast im `hello` ausdrücklich
`heartbeat: true` an. Der Host verarbeitet `ping` erst nach diesem Handshake.
Ein Host ohne Unterstützung für die Erweiterung akzeptiert das erweiterte
`hello` nicht. Der normale v1-Handshake bleibt verfügbar.

Nach dem Snapshot sendet der Gast `ping` mit einer pro Verbindung aufsteigenden
`nonce`. Der Host antwortet mit `pong` und derselben `nonce`. Eine abweichende
oder unaufgeforderte Antwort ist ein Protokollfehler. Nach der passenden
Antwort wartet der Gast eine Sekunde bis zur nächsten Anfrage. Fehlt die
Antwort fünf Sekunden lang, gilt der Host als ausgefallen. Der Diagnosegast
verwirft dann die Verbindung und folgt der oben beschriebenen Wiederverbindung.
Ereignisse können zwischen Anfrage und Antwort eintreffen. Lebenszeichen
ändern weder Zustand noch Sequenz.

Der Loopback-Host reiht den Snapshot und die nachfolgenden Ereignisse pro
Verbindung in Sequenzreihenfolge ein. Die Socket-Schreibvorgänge laufen
außerhalb der Zustandssperre. Pro Verbindung können 32 Frames warten.
Ist die Warteschlange beim Einreihen voll oder überschreitet ein
Schreibvorgang eine Sekunde, trennt der Host diese Verbindung.
Nach einer Wiederverbindung erhält er einen neuen autoritativen Snapshot.

Die Hülle ergänzt `version`. Vorschläge werden mit explizitem `target` und
`value` serialisiert. Für Vorschläge ohne Ziel wie `cutscene` ist `target` `null`.

Der Codec verarbeitet einzelne Nachrichten. Die TCP-Schicht schließt jede
v1-Nachricht mit LF ab und begrenzt die vollständige Zeile auf 1 MiB. Der Host
prüft das Ereignis und den resultierenden Snapshot vor der Zustandsübernahme.
Wenn einer der beiden Frames die Grenze überschreitet, erhält der Absender
einen Fehler und die Verbindung endet. Der zuletzt akzeptierte Snapshot
bleibt für die Wiederverbindung verfügbar. `observer.py --protocol-version 1`
verwendet denselben Handshake und prüft den ersten Snapshot. Der Observer
meldet eine Probe als bestätigt, wenn das zugehörige Ereignis im verifizierten
Strom angekommen ist. Dazu vergleicht er Spieler-ID und die kanonische
Nutzlast einschließlich Lauf-ID und Probensequenz. Andere Ereignisse
übernimmt er in seine Replik, während er auf die Bestätigung wartet.

Der REFramework-Observer ergänzt die lokale Probendatei um `available` und
`observed_at` (Unix-Sekunden). Bei `available: false` fehlen Position und
Rotation. Der Python-Observer überträgt dann beide Felder als `null` im
`player`-Vorschlag. Der Zeitstempel bleibt im Host-Zustand und wird beim
Rejoin mitgeliefert. Der Diagnosegast blendet zeitgestempelte Posen aus,
sobald ihre Quellprobe älter als fünf Sekunden ist. Für die Zeitprüfung
verwenden beide Prozesse die Systemzeit desselben Loopback-Rechners.
Ältere Spielerwerte ohne `observed_at` bleiben lesbar.

Im Repository-Verzeichnis `python -m unittest discover -s tests -v` ausführen.
Der Kompatibilitätstest vergleicht die Beispielnachrichten mit dem vorhandenen
Host und spielt sie über den Codec auf eine Replik. Der finale Snapshot wird
auch in einer neu verbundenen Replik wiederhergestellt.

## Steam-Posenbridge

Auf dem Steam-Posenkanal 883 tragen `hello` und `snapshot` zusätzlich eine
`request_id` aus 32 kleingeschriebenen Hexadezimalzeichen. Der Gast erzeugt
16 zufällige Bytes pro ausstehender Anfrage und behält die Kennung bei
Wiederholungen derselben Anfrage. Beim Verlust der lokalen Verbindung oder
nach dem Peer-Timeout einer aktiven Sitzung verwirft der Gast die Kennung.
Während er auf den angeforderten Snapshot wartet, behält er sie auch über
weitere Timeouts desselben Links. Der Host wiederholt die
Kennung im Snapshot. Der Gast nimmt den Snapshot nur für eine ausstehende
Anfrage an und prüft Sitzungskennung, Sequenz und Zustandsdigest vor der
Übernahme. Die Kennung gehört zum Nachrichtenumschlag. Der Zustandsdigest
deckt den Inhalt von `state` ab.

~~~json
{"version":1,"type":"hello","request_id":"fb009c0d87574138ad671931ad0747f3"}
~~~

Die Steam-Bridge aktiviert dieses Nachrichtenprofil ausdrücklich. Der
TCP-Handshake verwendet weiterhin seine v1-Nachrichten ohne `request_id`.
Für einen Steam-Test müssen beide Rechner dieselbe Bridge-Fassung nutzen.

Auf demselben Steam-Kanal trägt ein `propose` im Nachrichtenumschlag die
`session_id` des zuletzt geprüften Host-Snapshots. Der Host verwirft
Vorschläge mit einer anderen Sitzungskennung, auch wenn der Steam-Peer nach
einem Host-Neustart derselbe ist. Der v1-TCP-Vorschlag behält seine bisherigen
Felder.

~~~json
{"version":1,"type":"propose","session_id":"host-session","kind":"player","target":"claire","value":{"position":[1,2,3],"rotation":[0,0,0,1],"observer_sequence":9,"observer_run_id":"example-run","tdb":70,"observed_at":100}}
~~~

Mit `--lobby` sendet der Host zusätzlich `lobby_state` auf demselben Kanal.
Der Umschlag enthält `session_id`, eigene `sequence`, `digest` und `data`.
`data` enthält `host_id`, `guest_id`, `save_slot`, `settings`,
`revision`, `connected` und `ready`. Der Digest deckt diese Metadaten ab.
Die Lobby-Sequenz ist unabhängig von der Gameplay-Sequenz. Der Gast prüft
Sitzung, Rollen, Digest, Sequenz und Revision, bevor er seine Anzeige ersetzt.
Der Gast sendet `lobby_ready` mit `session_id`, `revision` und
booleschem `value`. Der Host ordnet die Meldung dem bestätigten Gast zu.

Auswahländerung, Verbindungswechsel und ein neuer Gast-Handshake verwerfen
die bisherige Bereitschaft. Wiederholungen desselben Handshakes ändern die
Revision nicht. Die beiden Nachrichtentypen gelten nur für das Steam-Profil;
TCP-v1 bleibt unverändert. Die gesamte Nachricht ist weiterhin auf 4096 Byte
begrenzt. Beide Teilnehmer müssen dieselbe Fassung verwenden.
[LOBBY_TEST.md](../LOBBY_TEST.md) beschreibt die Terminalbefehle und den
fehlenden Nachweis mit zwei echten Spielinstanzen.

Im nativen Katalogmodus enthält `data` zusätzlich `save_ref`. Ein
nicht verfügbarer oder nicht ausgewählter Stand wird durch
`{"available":false}` dargestellt. Ein verfügbarer Verweis enthält
exakt `available:true`, `mode:1`, `slot_id`, `timestamp` als
Dezimalstring, `scenario`, `label`, `difficulty_label` und
`metadata_digest`. Der Slot muss zu `save_slot` (`scenario:N`) passen.
Der Metadaten-Digest ersetzt keinen Digest der Speicherdatei.
Referenzänderung oder Quellenverlust invalidieren die Bereitschaft über
die Lobby-Revision. Bei nativer Auswahl verlangt der Host für `value:true`
zusätzlich `save_identity`. Der Gast berechnet den SHA-256-Digest aus der
kompakten, schlüsselsortierten UTF-8-JSON-Darstellung seiner lokalen Felder
`mode`, `slot_id`, `timestamp` und `scenario`. Der Host vergleicht ihn mit
dem Digest derselben Felder seiner aktuellen Auswahl. `value:false`
enthält keinen Digest; der Gast sendet die Rücknahme auch von selbst,
wenn der lokale Abgleich wegfällt. Beide Steam-Teilnehmer brauchen dieselbe
Fassung.

Für Slot 4 und Zeitwert `639300364800000000` aus Szenario 1 sieht die
Bereitschaftsmeldung so aus.

~~~json
{"version":1,"type":"lobby_ready","session_id":"host-session","revision":4,"value":true,"save_identity":"7a1fef813c3c0f6587e50353aa16202d2e3c9655711c5e963ed872b0c79ff624"}
~~~

[SAVE_CATALOG.md](../SAVE_CATALOG.md) beschreibt Quelle und Prüfumfang.

Mit der optionalen gemeinsamen Dateivorprüfung trägt `lobby_state.data`
zusätzlich `load_check`: zunächst `null`, danach exakt `attempt_id`
(32 Hexzeichen), `revision`, `save_digest` (64 Hexzeichen), `phase`
(`checking`, `prepared`, `starting` oder `failed`) und `reason`. Aktive Versuche
verlangen die aktuelle Revision, beide Bereitschaften und einen verfügbaren
nativen Verweis. Ein fehlgeschlagener Versuch darf seine ältere Revision
zur Diagnose behalten. Der Lobby-Digest deckt diese Felder mit ab.

Nur der Gast sendet `lobby_load_ack` mit exakt `version:1`, `type`,
`session_id`, `revision`, `attempt_id`, `sequence`, `save_digest` und
`accepted`. Bei nicht lesbarer lokaler Quelle sind `accepted:false` und
`save_digest:null` vorgesehen. Eine lesbare abweichende Datei meldet ihren
eigenen Digest; der Host verwirft den Versuch. Die Sequenz wächst je
Versuch. Doppelte/ältere Sequenzen verlängern keine Frist. Eine neue
Versuch-ID, Revision, Sitzung oder ein Fehler macht ältere Bestätigungen
unwirksam. Es werden keine Pfade, Dateiinhalte oder Wandzeitstempel
übertragen. Dieses Nachrichtenprofil ist nur für Steam freigeschaltet;
beide Teilnehmer benötigen dieselbe Fassung. Die neue Ladezulassung verwendet
`admission:1` in `load_check`. In `prepared` kann eine positive Gastbestätigung
außerdem `stage_id` (32 Hexzeichen) für den vom lokalen Spiel bestätigten
Ladebefehl tragen. Erst mit beiden Befehlen veröffentlicht der Host
`phase:"starting"` und `start:{"H":"…","G":"…","guest_ack_sequence":2}`.
Die Rollenwerte sind verschiedene 32-stellige Hexkennungen. Der Gast
prüft die Fünf-Sekunden-Frist auf seiner eigenen monotonen Uhr ab Versand
der genau bezeichneten Bestätigung. Nach Fristablauf oder Widerruf entfällt
`start` beim Host.
Die lokalen Prozess-, Pfad- und Schutzbelege bleiben auf dem jeweiligen
Rechner. `prepared` steht für gleiche geprüfte Save-Bytes. Die anschließende
native Pause und der Checkpoint-Abgleich bestätigen den eigenen Load.
Im geschützten Entwicklungsstarter trägt die positive `lobby_ready`-Nachricht
für einen ausdrücklich bestätigten Kampagnenstart auch `campaign_consent:true`.
Diese Zustimmung gilt für die Save-Identität und Revision derselben Nachricht.
Der Host kennzeichnet den dadurch gestarteten gemeinsamen Dateiversuch mit
`load_check.campaign_start:true`. Normale Dateiprüfungen enthalten das Feld nicht.
[SHARED_LOAD.md](../SHARED_LOAD.md) beschreibt Ablauf und fehlende Abnahmen.

## Entwurf für fragmentierte Welt-Snapshots

`snapshot_transfer.py` rahmt eine vollständige UTF-8-v1-`snapshot`-Nachricht
aus dem Basisschema für den Host. Der Gast erstellt für eine bestätigte
Host-Sitzung und eine ausstehende Anfrage einen `SnapshotReceiver`. Beide
Kennungen bestehen aus 32 kleingeschriebenen Hexzeichen, wie die bestehende
Host-Sitzungskennung und Steam-Anfrage-ID. Der Gast reicht ausschließlich
Pakete des als Host bestätigten Peers weiter. Der SHA-256-Digest dient der
Integritätsprüfung. Die Peer-Authentifizierung bleibt Aufgabe des Transports.

| Feld ab Byte | Größe | Bedeutung |
|---:|---:|---|
| 0 | 4 | Formatkennung und Version als Hex `52 32 53 01` |
| 4 | 16 | Sitzungskennung als Bytes |
| 20 | 16 | Anfrage-ID als Bytes |
| 36 | 8 | Autoritative v1-Sequenz, vorzeichenlos in Netzwerk-Byte-Reihenfolge |
| 44 | 4 | Gesamtlänge der v1-Nachricht in Bytes, vorzeichenlos in Netzwerk-Byte-Reihenfolge |
| 48 | 4 | Fragmentindex ab null, vorzeichenlos in Netzwerk-Byte-Reihenfolge |
| 52 | 32 | SHA-256 der vollständigen v1-Nachricht als Bytes |
| 84 | bis 4012 | Ausschnitt der v1-Nachricht |

Bei 117.483 Byte beginnen die ersten vier Felder zum Beispiel mit
`52325301`, `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`,
`bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` und `0000000000000001`.
Darauf folgen `0001caeb` für die Gesamtlänge und `00000000` für den
ersten Index. Diese Länge ergibt 30 Pakete mit höchstens 4096 Byte.

Ein Empfänger sammelt je Anfrage höchstens 1 MiB für fünf Sekunden lokaler
monotoner Zeit. Der Aufrufer ruft auch ohne eingehende Pakete `expire()`
auf und beendet die Anfrage bei Verbindungs- oder Mitgliedswechsel mit
`close()`. Bei Ablauf oder Abbruch braucht eine Wiederholung eine frische
Anfrage-ID. Fragmente dürfen in beliebiger Reihenfolge eintreffen.
Identische Dubletten ändern weder Inhalt noch Frist. Widersprüchliche
Fragmente für dieselbe Anfrage brechen sie ab. Der v1-Zustand wird erst
nach vollständigem Empfang und Prüfung von Paket-Digest, Sitzung,
Sequenz und Zustands-Digest im Modell übernommen.

### Abruf über die Steam-Pipe

Der optionale Terminaltest verwendet denselben bestätigten Steam-Peer und
dieselbe lokale Pipe wie der Posenpfad. Der Host gibt die Sitzungskennung
und eine frische Anfrage-ID am Terminal aus. Der Gast sendet eine
44 Byte lange Nachricht aus der Kennung `52 32 50 01` (Abrufversion 1),
16 Bytes Sitzungskennung, 16 Bytes Anfrage-ID und einem 4 Byte langen
Fragmentindex als vorzeichenloser Integer in Netzwerk-Byte-Reihenfolge.
Ein vollständiger Header für den Abruf ab Index 8 lautet zum Beispiel

~~~text
52325001 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 00000008
~~~

Der Host sendet höchstens acht Fragmente pro Abruf. Der Gast fragt den
nächsten Block an, sobald alle Fragmente des laufenden Blocks angekommen
sind. Der vorhandene Steam-Kanal sendet im Reliable-Modus. Ein Wechsel der
nativen Pipe-Epoche oder ein Ablauf nach 30 Sekunden beendet den Transfer. Der
Gast sendet den reservierten Index `ffffffff` nach vollständiger Prüfung
und Übernahme ins Modell. Beide Seiten brauchen dieselbe frische Anfrage-ID,
auch bei einem Wiederholungsversuch in derselben Sitzung.

[STEAM_POSE_TEST.md](../STEAM_POSE_TEST.md#optionaler-snapshot-test-über-steam)
enthält die Terminalbefehle.

### Checkpoint-Befund für einen vorbereiteten Ladeversuch

`--prepared-checkpoint` verwendet die Snapshot-Pipe und das vorhandene
v1-Framing. Die eigentliche Transfer-Sitzungskennung und Anfrage-ID
sind frisch. Die v1-Sequenz ist 1. Der einzige Zustandswert ist
`state.flags.prepared_load_checkpoint`. Er enthält die Lobbybindung,
den Dateidigest aus der Vorprüfung und den Digest aus dem nativen
Ladekopf.

~~~json
{"schema":1,"session_id":"lobby-session","revision":5,"attempt_id":"44444444444444444444444444444444","save_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","checkpoint_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
~~~

Guard-Kennung, lokale Mitgliedschaft, native Lade-ID und Save-Referenz
bleiben in den lokalen Dateien. Der Vergleich und seine Bestätigung
verwenden zwei Anfragen auf derselben Pipe-Epoche. Ihre Kennungen sind die
ersten und letzten 16 Byte aus `SHA-256` über die ASCII-Kennung
`re2-prepared-checkpoint-v2` und die je 16 Byte der ausgegebenen Transfer-
Sitzungskennung und Anfrage-ID. Der Host vergleicht seinen frischen
Ladekopf nach der ersten Gastbestätigung und liefert denselben Snapshot
als Bestätigung. Der Gast prüft dessen Inhalt und seinen frischen
Ladekopf, bevor er die zweite Anfrage bestätigt. Das Ergebnis gilt für
den abgerufenen Ladekopf.

Der Kampagnenstart verwendet danach einen weiteren Checkpoint-Abgleich
mit dem laufenden Speicherschutz und wartet auf eine Freigabebestätigung
des Gasts. Beide Bridges handeln vor dem Laden `resume_version: 2`
über `campaign_pose_capability` für ihren aktuellen Pose-Handshake aus.
Ältere Lobby- oder Posenverbindungen können ohne diese Bestätigung weiter
bestehen.

Die Freigabefolge auf der Snapshot-Pipe besteht aus Angebot (`R2O\x02`),
Annahme (`R2A\x02`) und Startbefehl (`R2R\x02`). Jeder Frame enthält
nach den vier Kennbytes die Sitzungskennung, die Versuch-ID und die
frischen 16 Zufallsbytes des Angebots mit je 16 Byte pro Feld. Alle
drei Frames benötigen dieselbe Pipe-Epoche und teilen die bestehende
Gesamtfrist. Der Gast bestätigt nach Prüfung seines lokalen Checkpoints,
seiner Pause und seines Speicherschutzes. Der Host prüft seine Belege
nach der Annahme, der Gast nach dem endgültigen Startbefehl nochmals.
Der erfolgreiche Versand des Startbefehls bestätigt dessen Einreihung
bei Steam. Bei Verlust des letzten Pakets bleibt eine einseitige
Freigabe möglich.

### Snapshot aus dem nativen Gegnerbericht

Der Host kann einen bestätigten Bericht mit Scope
`registered_and_stored_enemy_contexts` als v1-Snapshot anbieten. Die
Beobachtungssequenz wird zur Snapshot-Sequenz einer eigenen Diagnosesitzung.
Je GUID enthält `state.enemies` optional `registered` aus der Registry
und `storage` aus der separaten Speichertabelle. `registered.live.hp`,
`registered.stored.hp` und `storage.hp` bleiben eigenständige Felder.
Ein nativer Controller darf fehlen, und ein gespeicherter HP-Wert von
null setzt kein Todes- oder Eliminierungsflag.

`state.flags.native_enemy_observation` enthält Schema, Scope, TDB,
Host-Beobachtungszeit, Szenario, Ladeort und die nativen Gesamtwerte.
Der Host vergleicht Game-GUID und Save-GUID lokal mit dem Ladebeleg.
Lade-ID, Game-/Save-GUID, Inventar und Lua-Laufkennung bleiben lokal.
Der optionale Terminalvergleich enthält zusätzlich `checkpoint_proof`
als SHA-256 der kompakten, schlüsselsortierten JSON-Darstellung von
`scope`, `request_id` und `checkpoint`. Der Checkpoint besteht dabei aus
Game-GUID, Save-GUID, Szenario und Ladeort. Die frische Anfrage bindet
den Prüfwert an diesen Transfer. Beide Seiten bilden ihn aus ihrer
eigenen lokalen Ladebestätigung.

Vor dem Empfangs-ACK vergleicht der Gast den Prüfwert. Danach vergleicht
er GUID und Typkennung je Quelle, einschließlich InheritID bei vorhandenem
Kontext, gespeichertem Kontext, laufendem Controller und Speichertabelle.
Der Bericht hat `host_sequence`, `guest_sequence`, `sources` und
`live_candidates`. Ein Quellbefund sieht beispielsweise so aus.

~~~json
{"matched":1,"host_only":[],"guest_only":[],"identity_mismatches":[]}
~~~

Die Prüfsumme belegt übereinstimmende Ladekopfkennungen für diesen Abruf.
Der Checkpoint allein beschreibt keine aktuelle Raum- oder Objektbindung.
Der Befund ist eine Diagnose für die spätere native Anwendung.

### Laufende aktive Gegnerbeobachtung

`enemy_live.py` veröffentlicht den separaten Umfang
`active_enemy_controller_observations` als v1-Ereignis mit
`kind:"flag"` und `target:"native_enemy_live"`. Ein Ereignis ersetzt
die beobachtete aktive Menge vollständig. Der Host übernimmt den
vorhandenen Snapshot- und Ereignisdigest. Der Loopback-Host akzeptiert
für diese Diagnose ausschließlich lokale Veröffentlichungen.

Der Wert kann beispielsweise so aussehen.

~~~json
{"schema":1,"scope":"active_enemy_controller_observations","available":true,"reason":"ok","continuous":true,"observer_sequence":12,"observed_at":1794829058,"enemies":{"00000001-ffff-abcd-f0f1-f2f3f4f5f6f7":{"kind_id":4,"inherit_id":-1,"hp":0,"default_hp":100,"is_live":true,"is_dead":false}}}
~~~

`continuous:true` bezeichnet aufeinanderfolgende Beobachtersequenzen.
Der Wert bescheinigt keine durchgehend identische native Objektinstanz.
Eine Sequenzlücke beginnt mit einer neuen Momentaufnahme. Bei
Quellenverlust ist `available:false` und die aktive Menge leer. Eine
fehlende oder nicht mehr aktive GUID und null HP ergeben kein
Todesereignis. Unveränderte, fortlaufende Proben erzeugen kein zusätzliches
v1-Ereignis.

Im optionalen Steam-Test beginnt der laufende Abruf nach der Quittung für
den vollständigen nativen Gegner-Snapshot. Die separate Live-Sitzungs-ID
sind die ersten 16 Bytes von SHA-256 über das ASCII-Präfix
`re2-enemy-live-v1`, die 16 Bytes der ursprünglichen Sitzungs-ID und die
16 Bytes der ursprünglichen Anfrage-ID. Die Anfrage-ID je Abruf sind die
ersten 16 Bytes von SHA-256 über die Live-Sitzungs-ID und den bei 1
beginnenden Abrufindex als 32-Bit-Integer in Netzwerk-Byte-Reihenfolge.

Jeder Abruf verwendet die vorhandene Snapshot-Fragmentierung. Der
v1-Snapshot hat den Abrufindex als Sequenz und
`state.flags.native_enemy_live` als einzigen Zustandswert. Ab dem zweiten
Abruf bedeutet der Wert `null`, dass seit dem letzten Abruf kein neuer
Befund übertragen wird. Der Gast prüft und bestätigt jeden vollständigen
Abruf auf derjenigen nativen Pipe-Epoche, die den ersten Snapshot
abgeschlossen hat. Ein Abruf hat eine lokale Frist von fünf Sekunden.

Wenn beide Rollen `--death-evidence` angeben, verwendet der laufende
Abruf das Präfix `re2-enemy-live-v2`. Der vorherige Snapshot behält den
bisherigen Ablauf. Verfügbare Befunde enthalten zusätzlich die GUID-Map
`death_observations` mit höchstens 512 Einträgen. Jeder Eintrag enthält
`kind_id`, `inherit_id`, `hp`, `active`, `is_dead:true` und Sequenz
und Zeitpunkt des direkten Befunds als `observer_sequence` und `observed_at`.
Der Loopback-Host kann das Feld ebenfalls mit `--death-evidence` publizieren.

Der Steam-Host liest die native Quelle auch zwischen Anfragen. Er
übernimmt nur ausdrücklich gelesene Todesflags vorhandener
Gegnercontroller und behält für unveränderte Werte den ursprünglichen
Befund. Fehlt der Controller später, darf eine neue native Probe den
letzten Todesbefund bis zu drei Sekunden nach dessen letzter direkter
Bestätigung weiterführen. Eine neue Lesung mit `is_dead:false` für diese
GUID, ein Typwechsel, der Checkpoint-Wechsel oder der Verlust der Quelle
verwirft den Befund. HP und gespeicherte Gegnerwerte bleiben eigenständige
Beobachtungen.

Optional erzeugt der Gast nach jeder vollständigen Abfrage die lokale
Datei `re2_coop_guest_enemies.json`. Ihr Schema 1 enthält `source`
(`steam_enemy_live`), TDB, Sitzung, `generation` als lokale
Startzeit in Unix-Mikrosekunden, fortlaufende `sequence`, lokalen
`received_at`-Zeitstempel in Sekunden, `view` und `load`.
`view` enthält den bereits lokal gefilterten aktiven Befund.
`load` enthält bei Verfügbarkeit die lokale Lade-ID, Slotkennung,
den lokalen Checkpoint und Laufkennung/Sequenz des Gegnerlesers.
Diese Metadaten bleiben auf dem Gast. Bei Nichtverfügbarkeit ist
`load:null`.

REFramework verlangt eine höchstens drei Sekunden alte Datei. Ein
identischer wiederholter Beleg verlängert diese Frist nicht. Für
dieselbe Startzeit weist der Leser Sequenzrücksprünge und geänderte
Bytes unter derselben Sequenz ab. Der Leser gleicht Ladebeleg,
Checkpoint und die aktuelle lokale Beobachtung nochmals ab. Beispiel
für einen Eintrag im Rücklesebefund.

~~~json
{"kind_id":4,"inherit_id":-1,"host_hp":0,"local_hp":17,"host_is_live":true,"local_is_live":true,"host_is_dead":false,"local_is_dead":false}
~~~

Wenn das optionale Feld vorhanden ist, enthält die Rücklesedatei die
Host-Belege separat unter `state.host_death_observations`, auch für
GUIDs ohne aktiven Gastcontroller. Die Trefferliste `state.enemies`
liefert die Kandidaten für den HP-Adapter.

Die getrennte optionale Autorun-Diagnose für positive HP verwendet
denselben lokalen Beleg. Pro lokaler Stream-Generation und neuer
Host-Beobachtungssequenz prüft sie den aktuellen nativen Checkpoint
und die passende Instanz in der aktiven Gegnerliste. Der verifizierte
Setter `HitPointController.set_CurrentHitPoint(System.Int32)` setzt
einen absoluten positiven Wert. Der native Rücklesewert muss dem
Hostwert entsprechen und das Todesflag muss weiter falsch sein.
Der Adapter schreibt ausschließlich den HP-Wert. Tod, Wince,
gespeicherte Gegnerdaten und Schadensereignisse liegen außerhalb dieses
Schreibpfads.

Ein geschützter Einzelinstanz-Test am 17. November bestätigte diesen
unveränderten Adapter an einem echten Kampagnenzombie mit 770 → 769 HP,
Wiederholungsabwehr und erhaltenem Beleg nach Quellenverlust. Seine
Hostquelle war lokal erzeugt; es gab keinen Steam-Peer oder natürlichen
Treffer. [NATIVE_CAMPAIGN_HP.md](../NATIVE_CAMPAIGN_HP.md) grenzt den
Nachweis von der weiterhin offenen Zwei-Instanzen-Abnahme ab.

Das zusätzliche lokale Feld sieht beispielsweise so aus.

~~~json
{"reason":"ok","applied":1,"identical":0,"skipped":0}
~~~

Vor dem Setter prüft der Adapter die Frist erneut. Das äußere Feld
`last_application` der Rücklesedatei hält den letzten bestätigten
Schreibbefund für eine Host-Probe fest. Solange Sitzung, lokale Generation
und Host-Quellsequenz gleich sind, sammelt der Befund bestätigte Schreibvorgänge
auch über mehrere Empfangssequenzen hinweg. `applied` zählt die GUIDs.
Jede GUID enthält Typ, InheritID, HP vor und nach dem Setter, das
zurückgelesene Todesflag sowie die eigene `receipt_sequence` und
`applied_at`. Die entsprechenden Werte im Kopf beziehen sich auf den
jüngsten bestätigten Schreibvorgang. Erst ein bestätigter Schreibvorgang
für eine andere Host-Probe setzt den Befund neu auf. Bis dahin bleibt
er auch bei Quellenverlust oder Reset als historischer Befund lesbar.
