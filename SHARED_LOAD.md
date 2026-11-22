# Gemeinsame Spielstand-Vorprüfung

Der neue Pausenentwurf verlangt nach einem zugelassenen vorbereiteten Load
zusätzlich eine eigene bestätigte native Menüpause. Beide Spielinstanzen
bestätigen ihre lokale Ladeanforderung vor dem ersten nativen Load.
`--wait` meldet für
diesen Load erst mit passendem `load_hold` Erfolg. Der Checkpoint-Abgleich
prüft die Pause vor/nach dem Ladekopf und in beiden Transferphasen;
das Unterformat ist dafür 2. Die beiden Rechner benötigen dieselbe Fassung
einschließlich `re2_coop/prepared_load_pause.lua` und der aktualisierten
Skriptprobe. Fehlt die native Pausenprimitive, wird vor dem Load abgewiesen.
Dieser Entwurf hält die Spiele an und hat noch keine automatische gemeinsame
Rückkehr. Den Test durch Schließen der Testinstanzen beenden; manuelles
Fortsetzen widerruft den Pausennachweis. [PREPARED_LOAD_PAUSE.md](PREPARED_LOAD_PAUSE.md)
beschreibt Ablauf, native Einzelinstanz-Messung und weiterhin offene Grenzen.
Das installierte Verbindungstestpaket `4494ef2` wird damit nicht verändert.

Die Dateivorprüfung verbindet die lokale native Spielstandauswahl mit
einer Bestätigung durch beide Steam-Bridge-Teilnehmer. Der Status
`prepared` bestätigt zunächst gleiche Dateibytes. Eine optional
ausgelöste lokale Ladeanforderung nutzt diesen Versuch als Voraussetzung.

Der bisherige `save_ref.metadata_digest` deckt nur die Katalog-Metadaten
ab. Gleicher Slot, Zeitpunkt und Text sind kein Nachweis gleicher
Speicherdateien. Die neue ausdrücklich aktivierte Prüfung liest deshalb
die tatsächlich lokal vorhandenen Dateibytes auf beiden Rechnern.

## Ablauf

1. Host und Gast verwenden dieselbe Bridge-Fassung, einen frischen
   lokalen nativen Katalog und ein ausdrücklich angegebenes Datum.
   Der Host wählt einen verfügbaren nativen Slot. Beide melden sich
   für dieselbe Lobby-Revision bereit.
2. Der Host fordert `check-load` an. Seine Bridge validiert den aktuellen
   lokalen Katalogverweis und berechnet SHA-256 über die passende Datei.
   Sie veröffentlicht einen neuen zufälligen Versuch mit Sitzungskennung,
   Revision und Dateidigest im autoritativen Lobbyzustand.
3. Die Gast-Bridge löst diesen Slot ausschließlich in ihrem eigenen
   angegebenen Speicherordner auf. Modus, Slot, Zeitwert und Szenario
   müssen im eigenen datumsgefilterten Katalog passen. Lokalisierte
   Anzeigetexte müssen nicht gleich sein. Danach vergleicht sie die Datei.
4. Der Host übernimmt nur eine Bestätigung für die aktuelle Sitzung,
   Revision und Versuch-ID mit höherer Bestätigungssequenz. Bei passendem
   Dateidigest wird `load_check.phase` zu `prepared`. Das bedeutet nur:
   Beide lokalen Prüfpfade haben gleiche Dateibytes bestätigt.
5. Beide Seiten lesen die Quellen weiter. Der Gast sendet im Abstand von
   einer Sekunde eine neue Bestätigung; nur neue Sequenzen verlängern
   die Fünf-Sekunden-Frist auf der lokalen monotonen Host-Uhr. Es werden
   keine Rechneruhren verglichen. Der Host prüft seine eigene Datei
   ebenfalls mindestens einmal je Sekunde bei laufender Bridge-Schleife.
   Endet diese Prüfung bei oder nach Fristablauf, bleibt der Versuch als
   `guest_ack_expired` fehlgeschlagen. Auch eine wartende Bestätigung
   kann ihn anschließend nicht verlängern.
   Der Gast verlangt einen verifizierten Lobbyzustand aus den letzten
   drei Sekunden. Bei Ablauf blendet er die alte Vorprüfung aus, setzt
   die Bestätigungen aus und nimmt seine Bereitschaft für die letzte
   geprüfte Revision zurück. Steam-Posen und Heartbeats können dabei
   weiterlaufen. Der Gast kann sich nach einem frischen Lobbyzustand
   erneut bereit melden.
6. Quellenverlust, abweichende Bytes, neue Auswahl/Einstellungen,
   zurückgenommene Bereitschaft, Verbindungswechsel oder Fristablauf
   machen den Versuch ungültig. Ein fehlgeschlagener Versuch bleibt
   fehlgeschlagen; eine verspätete Bestätigung kann ihn nicht beleben.
   Eine neue Prüfung erhält eine neue Versuch-ID.

Die Dateien werden ausschließlich lesend geöffnet. Der Dateiname entsteht
lokal aus dem validierten Slot (`dataNNNSlot.bin`); eine Netzwerknachricht
liefert keinen Pfad. Der Ordner muss absolut sein. Symlinks, ein Ziel
außerhalb dieses Ordners, leere Dateien und Dateien über 32 MiB werden
abgewiesen. Dateiidentität, Größe und Änderungszeit werden vor/nach dem
Lesen geprüft, die Katalogidentität danach erneut. Ein Lese-/Metadatenfehler
liefert keinen erfolgreichen Digest. Das ersetzt keine Betriebssystemsperre
für einen späteren nativen Ladevorgang.

## Entwicklerbedienung

Nur in den bereits dokumentierten isolierten Testinstallationen verwenden.
Beide benötigen den Exporter `re2_coop_save_catalog.lua`. Das optionale
Argument bezeichnet jeweils den eigenen nativen `win64_save`-Ordner;
keine Speicherdatei wird kopiert oder übertragen.
Beim Gast verwendet die Bereitschaftsprüfung automatisch den Katalog
dieser Dateiquelle. Ohne Dateivorprüfung kann der Gast seinen Katalog
weiterhin ausdrücklich mit `--save-catalog` aktivieren.

```powershell
# Host, zusätzlich zu seiner vorhandenen Steam-Lobby:
python steam_pose_bridge.py --role host --pid $re2Pid --data "<RE2>/reframework/data" --lobby --save-catalog --lobby-save-slot scenario:4 --allow-save-date 2026-11-11 --load-save-directory "<eigener nativer win64_save-Ordner>"
# Gast, auf dessen Rechner mit dessen RE2-Prozess:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "<RE2>/reframework/data" --lobby --allow-save-date 2026-11-11 --load-save-directory "<eigener nativer win64_save-Ordner>"
# Auf beiden Seiten nach bestätigter Auswahl:
python lobby_control.py --data "<RE2>/reframework/data" ready yes
# Nur der Host:
python lobby_control.py --data "<RE2>/reframework/data" check-load
python lobby_control.py --data "<RE2>/reframework/data" status
python lobby_control.py --data "<RE2>/reframework/data" cancel-load-check
```

Ein Terminalbefehl bestätigt nur das Schreiben einer lokalen Anweisung.
Das autoritative Ergebnis steht unter `lobby.data.load_check`; auch
`fresh`, `connected`, Sitzung, Revision und Bereitschaft prüfen.
Ohne `--load-save-directory` ist diese Funktion deaktiviert. Ein Gast
ohne diese ausdrückliche Aktivierung bestätigt keine Datei; der
Hostversuch läuft ab. Diese Entwicklerfunktion hat noch keinen
zusätzlichen Knopf im Spielmenü.

## Lokale Ladeanforderung für einen vorbereiteten Versuch

Der geschützte Entwicklungsstarter verbindet die Lobby-Aktion **Kampagne
starten** mit der vorhandenen Vorprüfung. Der Gast stimmt der konkreten
Auswahl über **Für Kampagnenstart bereit** zu. Die normale Bereitschaft
ist weiterhin separat. Nach dem Dateivergleich stellt die Bridge auf jedem
PC genau eine lokale Ladeanforderung für denselben Versuch. Beide behalten
die Titelprüfung, die lokale Slotfreigabe und die bestehenden Schutzbelege.
Die Lobby blendet sich aus, sobald der lokale native Leseaufruf bestätigt
wird. Bei einer vorzeitigen nativen Ablehnung bleibt die Ansicht verfügbar.
Die manuelle Terminal-Vorprüfung bleibt als Diagnosepfad erhalten.
Nach Annahme des lokalen Starts wartet der geschützte Starter auf die
passende native Pause. Host und Gast vergleichen dann den Checkpoint automatisch
über die separate Snapshot-Pipe. Beide verwenden die Sitzungs- und Versuch-ID
des Ladeauftrags. Der Host bietet die Freigabe auf derselben Verbindung an.
Der Gast bestätigt das Angebot erst nach erneuter Prüfung von Checkpoint,
Pause und Speicherschutz. Der Host wartet auf diese Bestätigung, prüft
seinen lokalen Zustand und sendet dann den endgültigen Startbefehl. Der
Gast prüft seinen Zustand nochmals beim Empfang. Beide Bridges müssen
vor dem Laden dieselbe Version dieses Ablaufs bestätigen.

Ein abgelehntes oder verlorenes Angebot hält den Host in der Pause. Nach
der eigenen nativen Freigabe sendet jede Bridge einen Freigabebeleg pro
Sekunde über die Snapshot-Pipe. Sie belegt diesen Anschluss, solange der
Versuch läuft. Kampagnenposen benötigen einen aktuellen Beleg des Peers.
Bei ausbleibendem Beleg oder Verlust der nativen Verbindung versucht eine
bereits freigegebene Instanz, denselben Spielkontext wieder anzuhalten.
Die gemeinsame Freigabe und der erneute Weltabgleich nach Verbindungsabbruch
brauchen die Abnahme mit zwei echten Spielinstanzen. Details stehen unter
[Native Pause nach vorbereitetem Laden](PREPARED_LOAD_PAUSE.md).

Mit dem integrierten Gegnerabgleich prüft der Start zusätzlich den
Steam-Kampfkanal. Gegnerdaten und positive Gasttreffer werden nach der
beidseitig bestätigten Pause-Freigabe auf diesem eigenen Kanal übertragen.
Ein vollständiger Transfer verlängert seine Frist. Fehlt zehn Sekunden
lang die Bestätigung eines Transfers, endet lokal auch die Übermittlung
der Pause-Freigabebelege. Beide Seiten können so den bestehenden
Pausenpfad auslösen, solange der ursprüngliche Spielkontext verfügbar ist.

## Vergleich nach unterbrochener Kampagne

Wenn beide Instanzen erneut über Steam verbunden sind und ihre native
Pause nach der Unterbrechung noch bestätigt ist, lässt sich der aktuelle
Zustand im Terminal vergleichen. Der Host erhält beim Start die Kennungen
für den Gast.

```powershell
# Host
python steam_snapshot_transfer.py --role host --data "<RE2>/reframework/data" --pid $re2Pid --interrupted-checkpoint
# Gast mit den Kennungen aus dem Host-Terminal
python steam_snapshot_transfer.py --role guest --data "<RE2>/reframework/data" --pid $re2Pid --interrupted-checkpoint --session-id HOST_SESSION --request-id HOST_REQUEST
```

Beide Terminals zeigen getrennte Ergebnisse für `area` (aktuelles
Gebiet), `inventory` (Kernwerte des aktiven Spielerinventars),
`load_header` (Kopf des geladenen Spielstands), `enemy_live`
(Registry-Kontexte und laufende Controller), `enemy_storage`
(gespeicherte Gegnerkontexte, separate Speichertabelle und Killzähler)
und `doors` (Öffnung, Verriegelung und Speicherzustand der Türen in der
geladenen Szene). Inventar, Gegner und Türen stammen aus frischen
Beobachtungen nach bestätigter Pause. Beide PCs benötigen für diesen
Vergleich dieselbe Paketversion.
Bei weiterhin bestätigtem Speicherschutz sind Zähler für abgefangene
Autosaves aus dem Kampagnenlauf zulässig.
Ein falscher Startversuch, eine geänderte Verbindung oder der Verlust
der Pause bricht die Prüfung ab. `true` bestätigt die Übereinstimmung
der beobachteten Kategorie für diesen Versuch. Die Pause bleibt aktiv.
Der vollständige Weltabgleich benötigt noch weitere Weltobjekte, Rätsel,
Skripte und Zwischensequenzen sowie die Anwendung des Hostzustands.

## Manueller Ladepfad zur Diagnose

Auf beiden Seiten muss die aktuelle [Save-Guard-Probe](READONLY_LOAD.md)
in der isolierten Testinstallation aktiv und das Titel- oder
Kampagnenmenü bereit sein. Beide Teilnehmer verwenden dieselbe Paketfassung,
warten auf `prepared` und lösen dann den folgenden Befehl innerhalb von
20 Sekunden jeweils im eigenen Terminal aus. Der zuerst ausgeführte Befehl
wartet auf die zweite Anforderung.

```powershell
python readonly_save_control.py --data "<RE2>/reframework/data" --allow-save-date 2026-11-11 --load --prepared-lobby "<eigener nativer win64_save-Ordner>" --wait 30 scenario:4
```

Der Befehl vergleicht Slot und native Referenz, bindet die Kopie an den
aktiven Steam-Spielstandordner und berechnet den lokalen Dateidigest
erneut. Danach prüft er Lobbyrolle, Mitgliedschaft, Peer und deaktivierte
Steam Cloud am Plugin der gemeldeten Prozess-ID. Anschließend prüft er
Verzeichnisidentität, Guard und Lobby nochmals. Die Anforderung verwendet
das lokale Schema 3 von `re2_coop_save_policy.json`. Vor dem Schreiben
prüft er außerdem den laufenden Windows-Speicherschutz für diesen Ordner.
Dessen geschützter Block muss den RE2-Testprozess einschließen. Das Feld
`lobby_load` enthält `guard_run_id`, `game_pid`, `role`, `membership` mit lokaler
Sitzungskennung und Revision, die Lobby-`session_id`, `revision`,
`attempt_id` und `save_digest`. Die Befehls-ID ist für dieselbe
lokale Bindung stabil. Für den gemeinsamen Ladeversuch brauchen beide
Seiten die Zulassungsvariante `admission:1` des Steam-Profils v1.

Die Lua-Probe prüft die Bindung und die native Ladebereitschaft und meldet
die lokale Anforderung als `staged_load`. Der Host wechselt auf `starting`,
sobald beide vorbereiteten Befehls-IDs zum selben aktuellen Versuch gehören.
Die Startentscheidung endet mit der laufenden Fünf-Sekunden-Bestätigungsfrist.
Der kurz beschäftigte Katalog darf in dieser Phase die Auswahl nicht
zurücksetzen. Jede Bridge prüft den Spielstart, Steam-Mitgliedschaft,
Speicherpfad, Windows-Schutz und Cloud-Status vor ihrer lokalen Freigabe.
Lua benötigt sowohl ihren eigenen vorherigen Beleg als auch die passende
lokale Freigabe. Bei geänderten Daten lehnt sie die Anforderung ab.
Dieselbe Versuch-ID erreicht den lokalen Loader höchstens einmal je
Guard-Lauf. Für einen weiteren Ladeversuch beginnt der Host eine neue
Dateivorprüfung. `--wait` wartet auf `scene_loaded` der eigenen Lade-ID.
Ein Statuswechsel nach der Zulassung kann den bereits angelaufenen
nativen Lesevorgang weiterlaufen lassen. Die Dateiprüfung ersetzt keine
Sperre gegen spätere Dateiänderungen.

## Nativen Checkpoint nach dem Laden vergleichen

Beide Instanzen benötigen zusätzlich den
[nativen Ladekopfleser](LOAD_WITNESS.md). Nach beiden lokalen
`scene_loaded`-Bestätigungen und innerhalb von 120 Sekunden nach dem
jeweiligen nativen Ladebeginn den Checkpoint abrufen. Die Posen- und
Lobby-Bridge läuft währenddessen weiter.

```powershell
# Host
python steam_snapshot_transfer.py --role host --data "<RE2>/reframework/data" --pid $re2Pid --prepared-checkpoint
# Gast mit den vom Host ausgegebenen Kennungen
python steam_snapshot_transfer.py --role guest --data "<RE2>/reframework/data" --pid $re2Pid --prepared-checkpoint --session-id HOST_SESSION --request-id HOST_REQUEST
```

Erwartet wird `checkpoint_match: true` mit derselben Versuch-ID in
beiden Terminals. Als Vergleich dienen die SHA-256-Digests der frisch
gelesenen nativen Ladeköpfe desselben Lobbyversuchs. Das Werkzeug verwendet
die eigene Snapshot-Pipe. Der Gast prüft den ersten Snapshot gegen seinen
lokalen Ladekopf. Nach dieser Bestätigung liest der Host seinen Ladekopf
erneut und gibt den unveränderten Befund in einem zweiten Transfer frei.
Der Gast prüft seinen aktuellen Ladekopf nochmals, bevor er diesen
Transfer bestätigt. Beide Transfers gehören zur selben Pipe-Epoche und
teilen eine Gesamtfrist von 30 Sekunden. Beide Rechner müssen dieselbe
Fassung des Checkpoint-Werkzeugs verwenden.

Der Guard veröffentlicht die beim Ladeaufruf verwendete Bindung unter
`prepared_load`. Wenn Katalog oder Bestätigung während des Ladens
kurzzeitig ausfallen, bleibt damit derselbe ursprüngliche Versuch
vergleichbar. Die Lobby muss verbunden bleiben und dieselbe native
Mitgliedschaft, Auswahl, Sitzung und Versuch-ID zeigen. Ein neuer
Versuch oder `cancel-load-check` widerruft den Vergleich. Das gilt
auch für einen Abbruch nach einem vorübergehenden Katalogausfall.
Bei unterschiedlichen Checkpoints bleibt die positive Bestätigung aus.

Regressionstests prüfen beide Rollen sowie Katalogausfall, geänderte
Mitgliedschaft, fehlende oder abgelaufene Ladebelege und unterschiedliche
Checkpoints. Sie prüfen auch eine Checkpoint-Änderung auf jeder Seite
während der Bestätigung, einen Wechsel der Pipe-Epoche und ältere Clients.
Die Abnahme mit zwei echten RE2-Instanzen, der Spielerzustand,
Weltstillstand und die abgestimmte Spielfreigabe stehen aus.

## Nachweise und offene Grenzen

Die Python-Prüfungen verwenden synthetische Dateien. Zwei laufende
Bridge-Schleifen mit getrennten Daten-/Speicherordnern bestätigen gleiche
Bytes und verwerfen eine geänderte Gastdatei bei unveränderten Metadaten.
Weitere Fälle prüfen Sitzungs-/Revisionswechsel, Wiederbeitritt, alte
Versuche, fehlende/ungültige Quellen, Dateiänderung während des Lesens,
Abbruch, neue gegenüber doppelten Bestätigungen und lokale Fristen.
Sie rufen keine native Lade-/Speicherfunktion auf.

Der kombinierte Stand enthält außerdem drei abgegrenzte Beiträge von
bySenom, ohne deren ursprüngliche PRs zu mergen:

| Beitrag | Herkunft | Integration |
|---|---|---|
| Laufende Slotfreigabe vor überlappenden Befehlen schützen; Befehls-, Policy- und Lade-ID trennen | [#52, 7e54fc3](https://github.com/Maaviis/re2-remake-coop/commit/7e54fc39c44b5d97f9b476ab87deec4a73c2a6a3) | Einzelpatch auf #51 übernommen |
| Terminal wartet mit `--wait` auf die eigene native Befehls-/Lade-ID | [#53, f350f59](https://github.com/Maaviis/re2-remake-coop/commit/f350f598d437311b7ea181d55f8bf08f90ddc453) | Auf #52 aufgebaut; Einzelpatch übernommen |
| Lokaler Gastkatalog, Identitätsdigest, automatische Bereitschaftsrücknahme und Menühinweis | [#55, dec7f62](https://github.com/Maaviis/re2-remake-coop/commit/dec7f62ef870f0fa52551ab5d81b2f1a1b5c256f) | Mit Dateivorprüfung kombiniert; Gastkatalog der Dateiquelle wiederverwendet |

Aus der anschließenden Integration in #55
([1106aad](https://github.com/Maaviis/re2-remake-coop/commit/1106aadb035915ec7da1a3e0a50cac9d0368ca16))
sind zusätzlich die gemeinsame Identitätsfeldliste und der Bridge-Test
für Bereitschaftsrücknahme nach erneut erfolgreicher Dateiprüfung
übernommen. Die bestehenden Lade-/Befehlsänderungen bleiben erhalten.

123 Python-Tests und zehn Lua-Suiten bestehen im gemeinsamen Stand.
Zusätzlich wurde die Dateianbindung am 15. November 2026 in einer frischen
RE2-Instanz (Build 11636119, REFramework d1461375, TDB 70) gegen den
echten Katalog geprüft: Die freigegebene Datei vom 11.11.2026 ergab
wiederholt denselben SHA-256-Wert wie die geprüfte Sicherung; die neuere
Auswahl wurde vor dem Dateizugriff abgewiesen. Es gab keine Kampagnen-
Ladeanforderung, Tastatur-/Mauseingabe oder Bildschirmaufnahme. Nach
bestätigtem Prozessende wurden Originaldateien zurückgestellt; alle zwölf
Speicherdateien blieben bytegleich, keine neue erschien. Das bestätigt nur
die lokale Katalog-/Dateianbindung, keinen gemeinsamen Steam-Lauf.
Ein weiterer frischer Hintergrundlauf prüfte die übernommenen
Befehls-/Lade-IDs: `--load --wait` bestätigte den eigenen Abschluss als
`scene_loaded`. Während `closing_menu` wurde ein zweiter Arm-Befehl
mit demselben vorab datumsgeprüften alten Slotverweis im lokalen Postfach
abgewiesen (`load_in_progress`). Die erste Policy- und Lade-ID blieben
erhalten; es gab genau eine native Leseanforderung. Eine anschließende
Arm-Anforderung per `--wait` bestätigte ihre eigene neue Policy, ohne das
vorherige Ladeergebnis zu ersetzen. Kein Speicheraufruf wurde erfasst.
Nach Prozessende waren alle zwölf Speicherdateien bytegleich und die
Originalinstallation wiederhergestellt. Das belegt den Titelbild-Pfad
und die überlappende Arm-Abweisung während des Menüabschlusses. Die
anderen Überlappungsphasen sind weiter nur simuliert geprüft; Kampagnenmenü,
nativer Fehlerpfad und Gast-Menüanzeige bleiben offen.

Die Datei kann verschlüsselte oder kontogebundene Daten enthalten.
Gleiche Bytes beweisen weder die Nutzbarkeit unter einem anderen
Steam-Konto noch den gleichen bereits laufenden Weltzustand. Verschiedene
Bytes könnten umgekehrt denselben logischen Fortschritt darstellen;
dieser Entwurf verweigert dann die Bestätigung. Er entschlüsselt und
portiert nichts. Zwei echte Konten/Spielinstanzen und ein portabler
nativer Zustandsnachweis fehlen weiterhin. Private Pfade, Digests,
Speicherdateien und Testprotokolle gehören nicht ins öffentliche Repo.

Python- und Lua-Regressionen prüfen die lokale Ladezulassung mit
synthetischen Dateien und nativen Testdoubles. Abgelaufene oder
gewechselte Mitgliedschaften, nicht bestätigte oder wiederholte
Versuche und geänderte Bytes lösen keinen Aufruf des Testloaders aus.
Für die eigentliche Ladebarriere fehlen weiterhin die gemeinsame native
Abnahme des Kampagnenstarts, Fehlerbehandlung, Stillhalten beider Welten,
passende Szenen-/Spielerzeugen und der vollständige gemeinsame
Welt-/Inventar-/Fortschritts-Snapshot vor der Spielfreigabe. Der offene
Absturz aus [READONLY_LOAD.md](READONLY_LOAD.md) ist nicht behoben.
Gemeinsames Speichern, Rejoin und sämtliche Synchronisationskategorien
aus [STATUS.md](STATUS.md) bleiben Teil des Ziels.

Der optionale [native Ladekopf-/Inventarkernnachweis](LOAD_WITNESS.md)
ergänzt inzwischen frische, an die eigene native Lade-ID gebundene
Teilwerte aus der tatsächlich geladenen Instanz. Sein ausdrücklich
begrenzter Umfang ist kein vollständiger Weltdigest und hebt keine der
obigen Freigabeanforderungen auf.

Der [native Gameplay-Pausenbaustein](GAMEPLAY_PAUSE.md) bestätigt inzwischen
einen begrenzten Pause-/Rückkehrpfad in einer Instanz. Tatsächliche Spiel-,
Rekord- und Szenenzeit sowie die beobachtete Idle-Animation standen still;
die native Menüaktion schloss Pause und Oberfläche vor der Rückbestätigung.
Die automatische Rückkehrfrist gehört nur zur isolierten Terminalprobe.
Die Dateivorprüfung löst diesen Baustein noch nicht aus. Vollständiger
Weltstillstand, Cutscenes, Prozess-/Linkbindung, gemeinsame Zustandsanwendung
und Freigabe beider Instanzen bleiben erforderlich.
