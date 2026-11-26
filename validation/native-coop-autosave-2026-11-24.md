# Koop-Autosave im laufenden RE2-Prozess

Am 24. November 2026 schrieb RE2 einen neuen Autosave unter einem relativen Koop-Mount und lud denselben Slot nach der Rückkehr ins Titelmenü wieder bis zur Spielwelt. Mit dem nativen Schreibschutz aus der Lobby scheiterte bereits der vorausgehende Systemsave. Der Direktstart für zwei Spieler ist damit weiter offen.

## Vergleich in RE2

Steam-App 883710, Build 11636119, TDB 70. Das installierte Steam-ZIP aus PR #155 trägt den Paket-Commit `79113cb3d0608f813d0bf9ed76b04054f13647d1` und SHA-256 `fb367a051665f61c83a4cfb60d04cf80a080c372571760efff8e6b53bc17023b`. Zwei temporäre Lua-Testskripte instrumentierten die Installation. Der normale Steam-Start wurde bis zum Titel geprüft. Für die folgenden Schreib- und Ladeversuche startete der Supervisor dieselbe EXE auf einem separaten Windows-Desktop mit Steam-Anbindung. Die Steam-API bestätigte deaktivierte Cloud-Synchronisation.

| Versuch | Beobachtung im Spiel und auf der Platte |
| --- | --- |
| Absoluter Windows-Pfad in einen vorhandenen leeren Ordner | Der Getter bestätigte den Pfad. Der Systemsave wurde angenommen, endete mit Code 2 und erzeugte keine Datei im Ziel. |
| Relativer Mount `./coop-save-<Lauf-ID>`, Profil nur mit Systemdatei, ohne Szenario-Slots | Systemsave und nativer Autosave erfolgreich. RE2 schrieb unter `883710/remote/coop-save-<Lauf-ID>/`. Der gleichnamige Kontrollordner im Spielverzeichnis blieb leer. |
| Rückkehr zum Titel und Laden im selben PID | Leon A, Normal. Der Zeitstempel aus der nativen Slot-0-Beschreibung stimmte vor und nach der Rückkehr zum Titel überein. RE2 nahm `requestLoadGameData(1,0)` an, war beim Lesen beschäftigt und meldete danach gültige geladene Daten, Slot 0 und keinen Ladefehler. Anschließend waren Ladevorgang und Titel beendet, die Szene geladen und die Spielerfigur für Szenario 0 und Schwierigkeit 1 vorhanden. |
| Gleicher relativer Mount mit `SteamPipe.protect_campaign()` aus dem installierten Paket | Vor dem Systemsave meldete der native Guard zehn geschützte Methoden und null abgewiesene Aufrufe. Danach stand ausschließlich `FileWriteAsync` auf 1. Die Engine meldete Fehlercode 2 und der Zielordner blieb leer. Der Versuch endete vor „Neues Spiel“. |

Die drei Dateien des erfolgreichen Rückladeversuchs waren `data00-1.bin` (4.924 Bytes), `data000.bin` (651.056 Bytes) und `data021Slot.bin` (1.124 Bytes). Den Autosave forderte der Versuch nach dem Laden der ersten Szene ausdrücklich über `requestSaveGameDataAuto()` an. Ein durch Bewegung oder Spielfortschritt ausgelöster Checkpoint ist eine eigene offene Prüfung.

## Versuchsaufbau für Entwickler

1. Ein entbehrliches RE2-Profil und einen eigenen Testaccount verwenden. Bei beendetem RE2 Originalbaum und Steam-Dateicache sichern, Hashes und Verzeichnisidentität erfassen. Im Versuch verwendete der Supervisor `open_save_session`, eine Arbeitskopie mit ausschließlich der echten Systemdatei, den ACL-Schutz aus `protect_re2_test_saves.ps1` und offene Lesesperren auf den Dateien und auf `remotecache.vdf`. Er verifizierte Cloud-Status, Spielprozess, Steam-Speicherpfad und Schutz vor der Freigabe. Der Hintergrunddesktop stammt aus PR #152.
2. Pro Versuch eine frische 32-stellige hexadezimale Lauf-ID generieren. Je einen leeren Ordner `coop-save-<ID>` unter dem Steam-`remote`-Ordner und im Spielverzeichnis anlegen. Die beiden Lua-Dateien `tests/re2_coop_save_service_probe.lua` und `tests/re2_coop_isolated_autosave_driver.lua` nur für den überwachten Test als temporäre REFramework-Autoruns bereitstellen. Die Anfrage `re2_coop_save_service_probe_request.json` im REFramework-Datenordner enthält `run`, `background: true` und `mount: "./coop-save-<ID>"`.
3. Am Titel die Rückmeldung `re2_coop_save_service_probe_result.json` mit derselben ID und dem zurückgelesenen Ziel prüfen. Im Kontrolllauf bleibt der externe Schutz der Originale aktiv. Im Vergleichslauf zusätzlich die reguläre Plugin-Funktion `protect_campaign()` aufrufen und deren frischen prozessgebundenen Nachweis samt Zählern erfassen. Bei einer fehlenden Vorbedingung den Test beenden.
4. Der Supervisor gibt den Treiber mit `re2_coop_autosave_experiment_go.json` und derselben `run`-ID frei. `re2_coop_autosave_experiment.json` liefert Engine-Ergebnisse. Für Erfolg müssen Speichern, gültiger Leseabschluss und der erneute Weltübergang mit derselben Auswahl und demselben Slot belegt sein. Die zwei Zielordner separat inventarisieren.
5. Nur den Testprozess beenden. Nach Ende seines Speicherschutzes die temporären Skripte und Testanfragen entfernen, die Originale wiederherstellen und alle Hashes erneut vergleichen. Hier änderte Steam im ersten Versuch trotz deaktivierter Cloud seinen lokalen Dateicache. Nach den Versuchen stimmten sämtliche 23 Originaldateien, die Verzeichnisidentität und die SHA-256 des Caches mit dem Ausgangszustand überein.

## Grenze der Integration

Die isolierte Speicher- und Ladekette und das Verhalten des nativen Lobby-Schutzes erreichen E3. Der Direktstart über die ausgelieferte Lobby und die Wiederherstellung eines persönlichen Gastinventars sind als vollständige Funktionen E0. Es gab keinen zweiten Spieler und keinen E4-Lauf. Die Lua-Versuchstreiber gehören nicht ins Steam-ZIP.

Für die Lobby fehlt ein auf die konkrete Koop-Kampagne und den laufenden Prozess begrenzter Schreibpfad. Der heutige Steam-Guard weist asynchrone Schreibvorgänge generell ab. Außerdem fängt der Lua-Guard bei aktiver Ladefreigabe Speicheranforderungen ab. Ein weiterer Getter-Vergleich reicht nicht aus. Beim nächsten Integrationstest muss der erlaubte Auftrag im gebundenen Koop-Ordner landen, während Schreibversuche auf den Einzelspielerbestand und über bereits offene schreibbare Handles sicher scheitern. Anschließend stehen ein natürlicher Checkpoint und die bestätigte Rückkehr zum Einzelspielerprofil an.
