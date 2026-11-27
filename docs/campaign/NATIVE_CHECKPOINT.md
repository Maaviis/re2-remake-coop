# Natives Koop-Speichern und Fortsetzen

## Aktueller Policy-Nachweis: Schema 5 (E3)

Der eigene Reviewentwurf #173 bestätigt mit Build `17d862e` zusätzlich
die produktive lokale Policy und native Vormerkung: isoliertes Profil
ohne Szenariosaves → Import → 8,437 Sekunden/acht Erneuerungen → `arm`
mit Schema 5 → bestätigter Stagingbeleg → modellierte gemeinsame
Startfreigabe → genau ein Load bis Leon A/Standard/Karte 174/Gebiet 0.
Der produktive Ladekopfzeuge bestätigt den archivgebundenen Versuch
unter nativer Pause (Snapshot-Unterformat 4). Keine gemeinsame Freigabe
der Pause wurde erteilt. Elf Originalsaves blieben gesperrt; Originalprofil,
Dateibestand, Prüfsummen, Steam-Cache und ACL sind geprüft zurückgesichert.
[Bereinigte Messwerte](../../validation/native-checkpoint-schema5-policy-2026-11-27.json).

Der private Treiber musste seine modellierte Lobby unabhängig von den
Prüfungen veröffentlichen. Zuvor scheiterte der zweite `_prepared_lobby`-
Aufruf in `arm` mit `a fresh connected Steam lobby is required`; der
Bericht war 3,118 Sekunden alt. Der produktive Code und die Drei-Sekunden-
Fristen blieben für den erfolgreichen Lauf unverändert.

Die [Schema-5-Schnittstelle](CHECKPOINT_POLICY_V5.md) bleibt zur Entscheidung
bei Sasha (@bySenom). Automatischer Lobby-/Controller-/Capability-Ablauf,
normaler Steam-Neustart, neuer Lobbybeitritt und zwei verschiedene Konten
sind nicht abgenommen. Die [E2-CI](../../validation/checkpoint-schema5-regression-2026-11-27.json)
ist grün; deren synthetischer Merge `dc24dba` und 119-Dateien-Paket sind
vom lokalen 117-Dateien-E3-ZIP `17d862e` zu unterscheiden.

## Vorheriger lokaler Loader-Nachweis (`2ca28ce`)

Der explizite Checkpoint-Aufruf des nativen Loaders ist jetzt auf der aktuellen
main-Struktur in echtem RE2 nachgewiesen (E3, `2ca28ce`). Das tatsächliche
117-Dateien-Steam-ZIP lieferte die nativen und Lua-Komponenten; 52 Python-Tests
bestehen aus dessen eingebetteter Laufzeit. Eine isolierte Kopie nur mit
Systemdaten bestätigte vor dem Mount zweimal null Szenariosaves. Import,
acht Sekunden Bereitschaft mit acht Erneuerungen und der produktive lokale
Loader-Aufruf ohne Freigabeadapter erreichten im selben Prozess Slot 0,
Leon A, Standard, Karte 174/Gebiet 0 und native Pause: ein erlaubter,
kein verweigerter Load. Elf Originalsaves blieben separat gesperrt;
Originalprofil, Dateibestand, Prüfsummen, Steam-Cache und ACL sind geprüft
zurückgesichert. Lobby und Gast waren modelliert. Gemeinsame Ladepolicy,
Steam-Neustart/neue Lobby und zwei Konten sind weiterhin offen.
[Messbericht](../../validation/native-checkpoint-current-main-loader-2026-11-27.json)

## Host-Checkpoint im geschützten Koop-Ordner

Nach der beidseitigen nativen Startfreigabe kann der Host mit F9 das
Multiplayer-Menü öffnen und **Koop-Checkpoint speichern** wählen. RE2
führt `SaveDataManager.requestSaveGameDataAuto()` im aktuellen Prozess aus.
Die Bridge wartet auf einen neuen Zeitstempel von Szenario-Slot 0, die
erneuerte Autosave-Datei und den vollständigen, stabilen Index samt Systemdatei.
Ein identisch gebliebener Index muss nicht ersetzt werden. Noch ausstehende
Dateiaustausche werden innerhalb der bestehenden 33-Sekunden-Frist erneut geprüft.
Der Host sieht **Koop-Checkpoint auf diesem PC gesichert**, sobald die
Bridge das Manifest und die drei geprüften Dateien gemeinsam veröffentlicht hat.
Eine ältere Generation bleibt auch bei einem Fehler separat erhalten.
Nach einem normalen Steam-Neustart prüft die Bridge die Generationen des
aktiven Kontos erneut. Das Host-Menü zeigt Figur und Zeitstempel der
jüngsten gültigen Generation. Ein beschädigter neuerer Eintrag bleibt
bei dieser Auswahl unberücksichtigt.

Ein erhaltener Lauf von Build `098a8aa` erreichte `scene_loaded` auf
Karte 174. Der native Spielstandschutz und Lua meldeten denselben Prozess
und Koop-Ordner. Am Ende standen `rehold_failed` und
`interrupted_pause_lost` im Guard-Bericht. Im zugehörigen Ordner lag
nur `data000.bin` mit 268 Bytes. Die Systemdatei und der Slotindex
fehlten. Die Archivprüfung findet dort keine gültige Generation. Der
zeitliche Zusammenhang mit den protokollierten abgewiesenen Aufrufen
`saveGameSaveData` und `requestSaveSystemDataNoSaveIcon` ist offen.

Zur Diagnose gehören die Phase und der Fehler aus
`re2_coop_checkpoint_status.json` und der native Messwert `host_checkpoint`
in `re2_coop_save_guard.json`. Der Namespace und die aktuellen
Freigabebelege müssen bis zum Ende des Speicherns übereinstimmen.

### Natives Speichern und Rückladen (E3)

Paketstand `4adde3f` erzeugte in einer echten RE2-Instanz die Dateien
`data000.bin` (651.056 Bytes), `data021Slot.bin` (240 Bytes) und
`data00-1.bin` (7.564 Bytes). Der Speicheraufruf lief durch den
unveränderten nativen Koop-Guard. Die Freigabedaten der zweiten Rolle
waren im isolierten Komponentenversuch simuliert.

Eine frische Instanz las aus einer geschützten Arbeitskopie mit
ausschließlich diesen drei Dateien Slot 0 zurück. Leon A, Standard,
Karte 174 und ein vorhandener Spieler wurden bestätigt. Die
Originaldateien und der Steam-Dateicache blieben bytegleich.

RE2 lieferte nach dem Neustart den Slot-Zeitstempel
`639301214020000000`. Der unmittelbar nach dem Speichern im Speicher
gemeldete Wert war `639312399330000000`. Beide Werte entsprechen exakt
Steams Dateizeitstempel am jeweils verwendeten Speicherpfad.
Der strenge Loader verweigerte die zweite Kennung und
akzeptierte die aktuelle native Referenz der archivierten Arbeitskopie.
Für Fortsetzen muss deshalb die beim Laden beobachtete Slotreferenz
zusätzlich zur unveränderten Prüfsumme der archivierten Nutzdaten
bestätigt werden.

Der Dateivergleich verwendet für Autosave-Slot 0 `data000.bin`.
Die manuellen Slots verwenden weiterhin `dataNNNSlot.bin`.
Ein E3-Lauf mit `2824427` bestätigte für das archivierte Autosave
dieselbe SHA-256 über den vorhandenen `NativeSaveSource`-Dateivergleich
und erreichte in der frischen Instanz erneut die Spielwelt.

### Wiederholung und abgebrochene Anforderung (E3)

Build `68c9535` archivierte über `serve_host` einen echten Checkpoint.
Der Test beendete die isolierte eigene Instanz nach der zweiten
angenommenen nativen Speicheranforderung mit beobachtetem `busy=true`.
Eine nur im Testtreiber vorhandene Unterbrechung des nächsten Updates
von höchstens drei Sekunden machte diesen kurzen Zustand beobachtbar.
Erste und vier ältere Generationen blieben verifiziert, eine zweite
Generation erschien nicht. Das belegt diesen Abbruchpunkt; der Zeitpunkt
innerhalb eines physischen Schreibzugriffs wurde nicht geprüft.
Gast und gemeinsame Freigabe waren simuliert. Originaldateien,
Steam-Cache und Zugriffsrechte wurden geprüft zurückgestellt.
[Messbericht](../../validation/native-checkpoint-interruption-2026-11-26.json)

Die native Prüfung erkennt außerdem eine erfolgreich wiederholte,
bereits identische Datei. Sie vergleicht die Bytes vor dem Originalaufruf
und verlangt nach Abschluss dieselbe ursprüngliche Dateiidentität,
SHA-256, Pfad und private Zugriffsrechte. Ersetzte oder veränderte Dateien
widerrufen weiter die Freigabe. Leere eigene Reservierungen werden erst
nach dem Abschluss entfernt.

Ein neuer Arbeitsordner pro Sitzung kann die Steam-Dateianzahl ausschöpfen.
Die Kapazitätsmessung unterscheidet konfigurierte Grenze, aktuelle lokale
Einträge und persistierte Dateien. Der E3-Kontrolllauf verwendete einen
zuvor gesicherten bestehenden Testordner. Die künftige Fortsetzen-Vorbereitung
muss dessen Inhalt aus der ausgewählten unveränderten Generation herstellen
und unvollständige Arbeitsdateien gesondert behandeln. Die native Slotreferenz
ist anschließend neu zu lesen. Derzeit ist dieser gemeinsame Übergang
weiterhin zur Abstimmung mit Sasha offen.

Die Slotreferenz ließ sich in einer weiteren geschützten E3-Titelinstanz
auf Build `68c9535` neu erfassen. Der statische Aufruf
`SaveService.updateSaveFileDetailTbl(via.UserIndex)` mit Index 0 las nach
dem Mount-Wechsel den Leon-Checkpoint anstelle des ursprünglichen
Claire-Slots. Die Dateien blieben unverändert; es gab keinen Save- oder
Spielstand-Ladeaufruf. Der eigentliche archivgebundene Load im Koop-Mount
bleibt gesperrt und benötigt den oben beschriebenen gemeinsamen Übergang.
[Katalogmessung](../../validation/native-checkpoint-catalog-refresh-2026-11-26.json)

### Archiv im laufenden Prozess einsetzen (E3)

`e2427de` bestätigt `CheckpointWorkspace.prepare()` in einer geschützten
RE2-Instanz. Die drei Dateien einer älteren geprüften Generation wurden
über den bestehenden nativen Schreibschutz in den gesicherten vorhandenen
Test-Arbeitsordner eingesetzt. Dieser hatte eine andere lokale Kennung als
das Archiv. Jeder echte Steam-Schreibabschluss lieferte Ergebnis 1; alle
drei Zielprüfsummen entsprachen der Auswahl. Der Titel- und Schutzbeleg
blieb gebunden. Das Archiv wurde nicht verändert.

Die nachfolgende native Katalogerneuerung erreichte im selben Prozess
den gewählten Leon-Slot. Null Spielstand-Ladeaufrufe, kein Engine-Autosave,
zwölf bytegleiche Originaldateien samt Cache und geprüfte ACL-Rücksicherung.
Das Lobby-Modell und die Gegenstelle waren simuliert. Der direkte Versuch
der Ladezulassung scheiterte mit `isolated_new_game_required` in
`save_guard.allow`. Die Vorbereitung erteilt keine Ladefreigabe und ist
noch nicht automatisch mit der Fortsetzen-Menüauswahl verbunden.
[Messbericht](../../validation/native-checkpoint-workspace-2026-11-26.json)

`b589a03` verbindet diese Vorbereitung mit dem regulären Katalogbaustein.
Ein E3-Lauf mit den ausgelieferten Autorun-Dateien und ausschließlich
beobachtendem privatem Lua-Treiber bestätigt den fertigen Vorbereitungsbeleg.
Die lokale Referenz wird nach dem Import zu zwei verschiedenen Zeitpunkten
gleich gelesen und an Prozess, Mount, Lua-Lauf und Import gebunden.
Native Slot-Zeit und archivierter Speicherzeitpunkt sind weiterhin
verschiedene Werte. Der Beleg erteilt keinen Ladeauftrag.
[Autorun-Messbericht](../../validation/native-checkpoint-catalog-autorun-2026-11-26.json)

### Archivgebundener Ladevertrag zur Abstimmung mit Sasha

Die optionale lokale Vorbereitung beginnt jetzt mit:

```python
receipt = CampaignSetup(data, pipe, game_exit).enable_checkpoint(selection, revision)
```

Der Gast muss zuvor das vollständig geprüfte Archiv erhalten haben.
Der Aufruf prüft tatsächliches Steam-Profil, vollständige Lobbyauswahl,
Titelzustand und Schutz. Er benutzt den vorhandenen PID-gebundenen ACL-Helfer.
Ein bestehender ladefreier Titel-Mount wird weiterverwendet. Ohne Mount
wird die Kampagnenkennung des Archivs an den bestehenden nativen Mount-Aufruf
übergeben. Derselbe Checkpoint erzeugt beim nächsten Prozessstart damit
keine neue zufällige Arbeitskennung. Ein unbrauchbarer Ordner führt zum
Fehler; es gibt weder Löschung noch zufälligen Ersatz. Mehrere verschiedene
Kampagnen können weiterhin zusätzliche Steam-Dateien benötigen.

`e32622e` bestätigt diese Vorbereitung in E3 ab einem Titel ohne Mount.
Import und Katalogerneuerung sowie der anschließende private Loader-Adapter
erreichen dieselbe Welt und native Pause ohne zusätzlichen Arbeitsordner.
Archiv und Originalbestand samt ACL-Rücksicherung sind geprüft. Die
Vorbereitung selbst lädt nicht; der gemeinsame Controller muss den Beleg
weiterhin an denselben archivgebundenen Versuch und beide Pausen binden.
Der normale Steam-Neustart und die Gegenstelle sind damit nicht abgenommen.
[Messbericht](../../validation/native-checkpoint-setup-2026-11-26.json)

Während der Abstimmung beider Rollen darf der lokale Vorbereitungsbeleg
nicht nur einen neuen Zeitstempel erhalten. Für den Controller gibt es:

```python
readiness = CheckpointReadiness(data, pipe, solo, receipt, game_exit)
receipt = readiness.refresh()
```

Der Konstruktor verlangt den noch frischen eigenen Beleg. Jede Erneuerung
prüft zusätzlich erneut alle Archiv-/Arbeitsdateien, den abgeschlossenen
nativen Import, Katalog und dieselbe Prozess-/Schutz-/Lobbybindung. Der
Controller soll am Titel mindestens einmal pro Sekunde erneuern und vor
dem nativen Load damit aufhören. Die Dreisekundenfrist bleibt bestehen.
Ablauf, Uhr-Rücksprung und Quellenverlust schließen diesen Prüfer dauerhaft;
danach ist eine neue native Vorbereitung nötig. Ein anderer, inzwischen
veröffentlichter Beleg wird nicht überschrieben. Es wird kein Import
wiederholt und kein neuer Nonce oder Ladeauftrag erzeugt.

E3 auf `783d39e` bestätigt rund neun Sekunden mit acht Erneuerungen,
danach den nativen Welt-Wiedereinstieg und Pause mit demselben Nonce.
Archiv und Originalbestand samt ACL-Rücksicherung sind geprüft. Dies ist
noch kein automatischer gemeinsamer Controller und kein Zwei-Konten-Lauf.
[Messbericht](../../validation/native-checkpoint-readiness-2026-11-26.json)

Die lokale native Zulassung ist mit `329c22b` in E3 geprüft:

```lua
guard:allow_checkpoint(reference, preparation_id, guard_run_id)
guard:revoke_checkpoint(preparation_id)
```

Die Vorbereitung exportiert dafür zusätzlich ihre Lua-Laufkennung.
Der Aufruf verlangt drei Sekunden frische, zusammenpassende Import-,
Katalog-, Workspace- und Lobbybelege, den aktuellen Mount und die lokale
Slot-0-Referenz. Ein Nonce kann nur einmal armiert werden. Der Auftrag
gilt höchstens zehn Sekunden, verfällt bei Bindungsverlust und öffnet
keine mehrdeutige Ladefunktion. Im isolierten Test verwendet ein Adapter
für `readonly_loader` genau diesen Zusatzaufruf. Der bisherige Guard-
Aufruf `allow` bleibt für Koop-Mounts gesperrt.

Import, Katalogerneuerung, nativer Slot-0-Load und Welt-Wiedereinstieg
erfolgten im selben RE2-Prozess. Leon A, Standard, Karte 174/Gebiet 0,
Spielfigur und die anschließend gehaltene native Pause sind bestätigt.
Lobby und Gast waren simuliert; die gemeinsame Policy, die zwei Pausen
und die gemeinsame Freigabe sind damit nicht abgenommen.
[Messbericht](../../validation/native-checkpoint-inprocess-resume-2026-11-26.json)

Die korrigierten Vorbereitungskomponenten sind jetzt auch aus dem
tatsächlichen Steam-ZIP `eec876a` in E3 geprüft. Das frühere 104-Dateien-ZIP
ließ `checkpoint_catalog.lua` aus; der vorherige E3-Autorun-Lauf verwendete
das vollständige Testpaket. Der Exporttest und die CI verlangen den
Baustein nun ausdrücklich. [Messbericht](../../validation/native-checkpoint-steam-export-2026-11-26.json)

Die lokale Empfangsseite existiert als `GuestCheckpointArchive` (E2).
Der Aufrufer übergibt das ausgewählte Manifest, dessen kanonischen Digest
und einen `confirm`-Callback, der bei Verlust von Quelle, Auswahl oder
Verbindung eine Exception auslöst. Geordnete Blöcke werden ausschließlich
für die drei festen Dateinamen in einem nicht veröffentlichten Ordner
außerhalb Steam-Remote gesammelt. `finish()` bestätigt alle Bytes und
die Bindung vor dem atomaren Veröffentlichen. Der Einzelspielerbestand
und ein vorhandener Koop-Arbeitsordner bleiben dabei unverändert.
Eine Übernahme kann auch mit leerem lokalem Szenario-Katalog beginnen.
Der Callback ersetzt keine Steam-Authentifizierung. Der optionale
`checkpoint_transfer` nutzt jetzt den vorhandenen Snapshot-Transport.
`ArchiveTransferBinding(data, snapshot_pipe, solo, selection, role)` prüft
das tatsächliche geschützte Titelprofil und die vollständige Lobbyauswahl.
`exchange(request_id)` verwendet ausschließlich dieses Profil; Host und
Gast benötigen denselben frisch vereinbarten Transfernonce. Die native
Peer-Epoche bleibt über alle Phasen gebunden. Es gibt keinen neuen nativen
Pakettyp. [Profil und Grenzen](../../bridge/protocol/README.md#entwurf-natives-checkpoint-archiv-über-den-snapshot-kanal)

32 gezielte E2-Tests bestätigen den Austausch und Fehlerfälle mit
serialisierten Snapshot-Paketen, ohne echte Steam-Gegenstelle. Vor dem
Aufruf müssen beide Bridges die Unterstützung des Profils und denselben
Nonce vereinbaren. Capability-Aushandlung und der automatische Aufruf
durch den gemeinsamen Fortsetzen-Auftrag sind noch nicht implementiert.
Die aktuelle gemeinsame Ladepolicy bleibt unverändert.

Die automatische gemeinsame Menü-/Controller-Anbindung ist noch nicht implementiert.
Der lokale Schema-5-Pfad liegt als [Reviewentwurf](CHECKPOINT_POLICY_V5.md) vor.
Die bestehende Auswahl
`settings.coop_checkpoint` aus main bleibt der gemeinsame Bezug. Ihr
Manifest-Digest bezeichnet die drei Archivdateien unabhängig von lokalen
Slot-Zeitstempeln oder Arbeitsordnerkennungen.

Der lokale native Loader hat im Integrationsentwurf einen expliziten optionalen
Aufruf `loader:start(reference, request_id, {preparation_id, guard_run_id})`.
Dieser verwendet `guard:allow_checkpoint` statt eines Testadapters und verlangt
einen aktuellen nativen Import-/Katalogbeleg. Ein abgelehnter nativer Request
oder fehlgeschlagener Ladeübergang widerruft die zugehörige Freigabe. Bestehende
Aufrufe mit zwei Argumenten behalten die gewöhnliche Slot-Prüfung. Dieser
Baustein ist mit `2ca28ce` in E3 auf der main-Zusammensetzung geprüft. Der
Produktions-Probe des Reviewentwurfs verwendet ihn seit `17d862e` für
Schema 5. Der automatische Lobbycontroller muss die Vorbereitung und
gemeinsame Startfreigabe noch an diesen lokalen Pfad anbinden.
Betroffen sind der Loader aus #155/#156, der Probe-Aufrufer und der gemeinsame
Ladecontroller. Sasha entscheidet über die Übernahme dieser Erweiterung.

Vorgeschlagen ist `arm(..., prepared_lobby=..., checkpoint={namespace,digest})`.
Dieser Pfad benötigt einen aktuellen Vorbereitungsbeleg mit exakt dieser
Auswahl und lokalem Slot 0. Er muss die tatsächlichen Dateien und die native
Referenz vor dem Auftrag erneut prüfen. Der gemeinsame Ladeversuch verwendet
den Archiv-Digest; beide Rollen behalten ihre eigenen nativen Referenzen.
Eine neue Policy-Version soll Checkpoint, lokale Referenz und vorhandene
Prozess-/Lobby-/Pausenbindung gemeinsam enthalten. Die allgemeine Sperre
von Slot-Loads in einem neuen Kampagnen-Mount darf dadurch nicht entfallen.

Für den Gast muss der neue Transferbaustein noch in diesen Auftrag
integriert und mit einer echten Steam-Gegenstelle geprüft werden. Erst
nach vollständiger Prüfung gegen den angekündigten Digest entsteht eine
unveränderliche lokale Generation. Der Szenario-Katalog des Einzelspielerprofils
darf dabei leer bleiben. Erst danach erfolgen der lokale Import, die native
Referenzerfassung und die beidseitige Ladebarriere. Ob RE2 diese Daten unter
einem anderen Steam-Konto tatsächlich lädt, muss E4 nachweisen.

Nach dem Laden bleiben beide nativen Pausen aktiv, bis der vorhandene
Weltvergleich und die gemeinsame Freigabe denselben archivgebundenen
Versuch bestätigen. #155/#156, der Guard, der Ladeauftrag und die
Checkpoint-/Lobby-Bridges sind betroffen. Sasha entscheidet über diesen
gemeinsamen Übergang und die Integration; der Vorschlag erweitert keine
der aktuellen Ladeberechtigungen.

### Abnahme mit zwei Steam-Konten (E4, ausstehend)

Die lokale Voraussetzung eines leeren Szenariokatalogs ist bereits in
einem isolierten E3-Lauf bestätigt: nur Systemdaten im Solo-Profil,
native Katalogerneuerung mit zweimal null Einträgen vor dem Mount,
danach Import und Welt-Wiedereinstieg samt Pause. Originalprofil und
Steam-Dateicache wurden geprüft zurückgesichert. Native Lobbyrolle war
Host auf demselben Konto. Die folgende Zwei-Konten-Abnahme bleibt nötig;
insbesondere ist die kontenübergreifende Verwendbarkeit der Dateien offen.
[E3-Messbericht](../../validation/native-checkpoint-empty-profile-2026-11-27.json)

1. Dasselbe Steam-ZIP auf beiden PCs installieren und seine SHA-256
   vergleichen. Jeweils ein isoliertes Profil mit initialisierten Systemdaten
   und deaktivierter RE2-Cloud verwenden. RE2 beenden, Originaldateien
   einschließlich Steam-Dateicache sichern und ihre Prüfsummen erfassen.
   Das Gastprofil braucht für diesen Versuch einen leeren Szenario-Katalog.
2. Beide starten RE2 regulär über Steam. Der Host lädt den Gast ein.
   Eine geschützte neue Kampagne starten. Beide Spieler bestätigen Ort,
   Figur und gegenseitige Bewegung. In der Freigabediagnose muss auf
   beiden Seiten `paired` stehen. Scheitert der Start vorher, je Rolle
   den letzten Übergang in `re2_coop_campaign_release_status.json` erfassen.
3. Der Host speichert am vereinbarten Ort über F9. Meldung, native
   Slotnummer, Zeitstempel und Manifestkennung festhalten. Einen weiteren
   Speichervorgang im entbehrlichen Profil unterbrechen. Nach dem Beenden
   beider Prozesse alle drei Dateien der letzten vollständigen Generation
   erneut gegen deren Manifest prüfen.
4. Für die noch zu integrierende Funktion **Fortsetzen** beide Spiele
   regulär über Steam öffnen und eine neue Lobby erstellen. Der Host
   wählt die zuvor gesicherte Generation. Auf dem Gast bleibt der
   Einzelspieler-Katalog leer. Vor der Auswahl und nach dem Wiedereinstieg
   dieselben lokalen Prozess-IDs nachweisen. Die aktuelle native
   Slotreferenz zusätzlich an die Prüfsumme der ausgewählten Generation
   binden. Speicherzeitpunkt und nativen Slot-Zeitstempel getrennt
   protokollieren. Figur, Schwierigkeit, Ort und gegenseitige Bewegung
   mit Schritt 3 vergleichen.
5. Beide Spiele schließen und auf beiden PCs den rückgesicherten
   Einzelspielerbestand und den Dateicache mit Schritt 1 vergleichen.
   Speicherdateien bleiben auf den Testrechnern.
