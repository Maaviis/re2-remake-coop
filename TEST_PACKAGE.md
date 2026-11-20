# Geschütztes Testpaket

## Gemeinsamer Download aus CI

Der Workflow `Protocol tests` erstellt nach den Python-/Lua-Prüfungen und
den Windows-/Native-Prüfungen ein Artefakt `re2-coop-test-QUELLCOMMIT`.
Der Windows-Job baut beide DLLs, prüft die festgelegte portable Python-Datei,
baut das Paket und prüft dessen Imports und Manifest mit der eingebetteten
Laufzeit. Anschließend enthält der Download genau ein Paket-ZIP und seine
`.zip.sha256`-Datei. Die Jobzusammenfassung verlinkt diesen Download; die
Aufbewahrungsfrist beträgt sieben Tage.

Beide Rechner verwenden denselben Download und vergleichen den ZIP-Hash
mit der beiliegenden Datei. Der genaue CI-Quellcommit steht zusätzlich im
Paketmanifest; bei Pull Requests kann dies der von GitHub geprüfte Mergecommit
sein. Der Export enthält ausschließlich geprüfte Manifestdateien. Lokale
Installationszeiger, zusätzliche Dateien und persönliche Spielstände werden
nicht aufgenommen. Fehlerhafte Dateien und Verknüpfungen brechen den Export ab.

CI prüft Build, Imports, Dateihashes und automatisierte Verträge. Die native
Paketprüfung und der Zwei-Konten-Test behalten jeweils ihre eigene Abnahme;
ein neuer CI-Download gilt nicht allein dadurch als in RE2 geprüft.

### Nativ geprüfter CI-Download vom 20. November 2026

Der [Download aus Lauf 44649281694](https://github.com/Maaviis/re2-remake-coop/actions/runs/44649281694/artifacts/14588959730)
enthält das Paket zur CI-Quelle `9e3f349de2917e0b8d205b9c9b8dbeebef104c6a`.
Sein Git-Baum stimmt mit dem überprüften Stand `d00a833` überein. ZIP-Hash,
Manifest, alle 134 Archivdateien und die 22 installierbaren Mod-Dateien wurden
nach dem tatsächlichen Download geprüft. Der ZIP-SHA-256 ist
`f00fa0b59dac6d9654f1b795dc5c684b9e581b0530a182037538f09006efa2a2`.
Das Artefakt ist bis 27. November 2026 aufbewahrt.

Anschließend liefen die unveränderten Befehle dieses heruntergeladenen Pakets
mit seiner eigenen Python-Laufzeit 3.13.17 in einer echten RE2-Instanz:
Installation mit Freigabe 2026-04-08, Hoststart, private Lobby per Terminal,
Load des lokalen alten Slots 4, Status, Stop und Deinstallation. Native API
und Bridge bestätigten `owned`; fünf unterschiedliche native Sequenzen,
ein erlaubter Load und null verweigerte Loads wurden erfasst. Alle 23
kopierten Speicherdateien blieben auch nach Spielende bytegleich.

Der Lauf verwendete wieder die private Vorbereitung mit isolierter aktiver
Kopie, zusätzlichem ACL-Schutz und deaktivierter RE2-Cloud. Die 24 ursprünglichen
Steam-App-Dateien, 31 Framework-Dateien und fünf Konfigurations-/Logdateien
sowie die ursprüngliche Cloud-Einstellung wurden vollständig zurückgestellt.
Der tatsächliche Paket-Uninstaller meldete seinen abgeschlossenen Rückbau.
Kein RE2-Prozess bleibt aktiv. Gast, zwei Konten und gemeinsames Spielen
bleiben mit diesem CI-Download unbestätigt. Die Abnahme bezieht sich genau auf
das verlinkte Artefakt; spätere Builds behalten ihre eigene Prüfgrenze.

## Paketprüfung vom 20. November 2026

Das Paket aus `88ceb931aea6cdc2dbbac6300d7ab2ca1e4fd826` verbindet den
integrierten Stand #120 mit einer an die Installation gebundenen Datumsfreigabe
und der korrigierten Wiederinstallation aus #121. Es enthält 132 geprüfte
Paketdateien, davon 22 installierte Mod-Dateien, sowie das Manifest. Die
Original-Laufzeit Python 3.13.17 wird mit dem festgelegten SHA-256 geprüft.
Das weitergebbare ZIP enthält ausschließlich diese Manifestdateien und das
Manifest selbst; der lokale Installationszeiger bleibt ausgeschlossen.

Der native Paketlauf verwendete die unveränderten Paketbefehle `install`,
`host`, `load`, `status`, `stop` und `uninstall` mit der enthaltenen Python-
Laufzeit. Eine eigene RE2-Instanz lief auf Build 11636119, TDB 70 und
REFramework d1461375. Für diesen Lauf lag eine isolierte aktive Steam-Kopie
unter zusätzlichem ACL-Schutz, und RE2-Cloud war vorübergehend deaktiviert.
Diese Vorbereitung erfolgt durch den privaten Testhelfer und wird durch die
Paketbefehle nicht automatisch für andere Installationen eingerichtet.

| Prüfung | Befund |
|---|---|
| Installation | Speichert die explizite Freigabe 2026-04-08; Pakethashes bleiben unverändert |
| Hoststarter | Startet das eigene RE2-Kind mit vererbten Dateisperren; beide Schutzbelege und Host-Bridge werden bestätigt |
| Steam-Lobby | Terminalbefehl erstellt eine private Lobby; native Schnittstelle und Bridge melden `owned`; keine Einladung versandt |
| Load | Tatsächlich vorhandener alter Slot 4 vom 08.04.2026 erreicht `scene_loaded`; fünf unterschiedliche native Sequenzen, ein erlaubter und null verweigerte Loads |
| Speicherdateien | Keine gezählte Engine-Speicheranforderung; alle 23 kopierten Dateien bleiben auch nach Spielende bytegleich |
| Rückbau | Echter Paket-Uninstaller bestätigt `restore_complete`; 24 ursprüngliche Steam-Dateien, 31 Framework-Dateien und fünf Konfigurations-/Logdateien sind bytegleich zurückgestellt; ursprüngliche Cloud-Einstellung wieder aktiv |

Die erste Sofortprüfung sah bei einem nativen `owned` einen vorübergehend
abweichenden Bridgebericht. Die Diagnose erfasste die tatsächlich veröffentlichten
Statuswechsel. Außerdem zählte der Testhelfer wiederholte Lesezugriffe derselben
nativen Sequenz mit. Der abschließende Lauf wartet auf fünf unterschiedliche
Sequenzen und die begrenzte asynchrone Statusaktualisierung. Er bestand ohne
Änderung der Paketimplementierung oder Schutzbedingungen. Rohberichte,
Diagnosehelfer und persönliche Dateien werden nicht veröffentlicht.

Die neue Wiederinstallation wurde zusätzlich in künstlichen Dateibäumen
geprüft: bestätigten Rückbau erhalten, vorheriges Paket archivieren,
Kopier-/Umbenennungsfehler zurücknehmen und aktive, unbekannte, unterbrochene
oder verknüpfte Installationen abweisen. `active=false` allein reicht nicht
als Wiederherstellungsbeleg. Lokal bestanden 272 Python-Tests, 20 Lua-Suiten,
beide nativen Builds und alle drei CTests. Das unabhängige Review bestätigte
54 fokussierte Tests ohne weitere Befunde.

Gaststart, zwei echte Konten, Einladungsannahme, Peer-Transport, gemeinsames
Laden und steuerbare Koop-Spieler wurden mit diesem Paket noch nicht abgenommen.

## Frühere Paketfassung

Die Paketfassung aus `4494ef28d5967e5eef0cdaa514a1eb3ca1857c14`
enthält den Integrationsstand aus #87 und die Speicherabsicherung aus #103.
Sie dient dem Steam-Verbindungs- und Posentest in einem festen Raum.
Eine gemeinsame Koop-Kampagne, ein steuerbarer zweiter Charakter,
vollständiger Kampf und synchronisierte Cutscenes sind nicht abgenommen.

Die [Anleitung](tools/test_package/ZUERST_LESEN.md) beschreibt beide PCs,
Installation, Start, alten Test-Save, Testende und Rückbau. Der Installer
sichert Originalmods und persönliche Saves lokal. Das weitergebbare ZIP
enthält nur die Dateien aus dem Paketmanifest und das Manifest selbst;
Installationszeiger, Sicherungen, Protokolle und Testzustände werden ausgelassen.

## Bestätigt am 17. November 2026

Windows x64, RE2 Build 11636119, REFramework d1461375/TDB 70 und die tatsächlich
enthaltene portable Python-Laufzeit 3.13.17 wurden verwendet. Die zwei Rollen
liefen **nacheinander auf einem PC**, ohne simulierten Peer.

| Prüfung | Befund |
|---|---|
| Installer | Originalordner unverändert gesichert; zwölf Save-Dateien kopiert und per SHA-256 geprüft |
| Hoststarter | Eigener direkter RE2-Prozess; native Steam-Sperre und vererbte Dateisperren aktiv |
| Host-Lobby | Private Steam-Lobby erfolgreich erstellt; kein Einladungsversand |
| Host-Load | Ausschließlich der freigegebene alte Slot 4 vom 11.11.2026; `scene_loaded`, frische Spielerpose, ein erlaubter Load und null verweigerte Loads/Speicheranforderungen |
| Gaststarter | Frischer eigener Spielprozess; Rolle G wartet ohne Einladung, beide Schutzschichten aktiv, null Loads |
| Testende | Beide Bridges beendet, jeweils nur die eigene bestätigte Instanz geschlossen; nach jedem Lauf zwölf unveränderte Dateien |
| Nicht geprüft | Zwei Konten, Einladung/Annahme, Marker auf dem zweiten PC, Rejoin und nativer Autosave-Schreibpfad |

Im ersten zusammengesetzten Lauf trat ein echter Windows-Lesekonflikt beim
Ersetzen des Schutzstatus auf. Die Bridge brach ab; die vererbten Sperren
blieben im laufenden Kind bestehen. Die korrigierte Fassung verwendet den
vorhandenen atomaren Writer mit begrenzter Wiederholung. Zwei Tests an
künstlichen Dateien prüfen kurzen und dauerhaften Lesekonflikt. Ein späterer
CI-Fehler betraf nur den Vergleich von 8.3-Kurzpfaden im simulierten
Kopierfehler; die beiden Testpfade werden nun vor dem Vergleich aufgelöst.

## Weitere Integrationsarbeit

Der Paketstarter unterstützt nun `install --allow-save-date YYYY-MM-DD`.
Die lokale Freigabe wird vor der Installation auf ein gültiges Kalenderdatum
in genau diesem Format geprüft und gespeichert. Lobbykatalog und Ladebefehl
lesen dieselbe Einstellung. Alte Installationen ohne dieses Feld behalten
den bisherigen Filter 2026-11-11. Host-/Gaststart und Load nehmen keine
Datumsüberschreibung über die Kommandozeile an. So kann dasselbe Paket mit
eigenen vorher freigegebenen alten Saves auf beiden Rechnern geprüft werden.

Am 20. November wurden #103 und #117 im Quellenzweig zusammengeführt und
die Schutzbelege mit dem vorbereiteten Load, der Pause und den beiden
Checkpoint-Phasen verbunden. Die oben beschriebene lokale Paketprüfung von
`88ceb93` ergänzt inzwischen die ältere Abnahme von `4494ef2`. Der kombinierte
Paketstand muss weiterhin mit zwei Konten auf beiden Rechnern geprüft werden.

#93–#102 sind getrennte Entwicklungszweige und keine Bestandteile dieser
Paketfassung. #95/#100–#102 verwenden unter anderem ACL-Schutz, Cloud-Prüfung,
aktive Steam-Savepfade und vorbereitete gemeinsame Checkpoints. #103 verwendet
vererbte Handles, eine native RemoteStorage-Vtable-Sperre und an den Start
gebundene Ladebelege. Diese unterschiedlichen Schutz- und Anforderungsformate
wurden im neuen Quellenstand abgeglichen. Keiner der PRs wurde durch die
Paketprüfung nach `main` gemergt.

Für einen vorbereiteten Test muss die aktive isolierte Kopie zusätzlich
unter `scripts/protect_re2_test_saves.ps1` stehen; die Schutzfunktion bleibt
während des kompletten Spiels geöffnet. Der Starter vererbt dann seine
Dateihandles an RE2. Der bisherige Paketknopf `Spielstand-laden.cmd` bleibt
eine einzelne lokale Leseprobe. Der vorbereitete Load verwendet den
Repository-Befehl `readonly_save_control.py --prepared-lobby` mit deaktiviertem
Cloud-Status und gültiger gemeinsamer Lobby. Der Marker der ACL-Sperre allein
ersetzt die beiden Startbelege nicht.

Der nächste Nutzertest braucht auf beiden PCs exakt dasselbe Paket und
einen abgesicherten eigenen Save im selben Raum. Ohne passenden freigegebenen
Save bleibt der Lobbytest möglich. Für normalen Kampagnenfortschritt zuerst
RE2 schließen und die Testinstallation über `Entfernen.cmd` zurückbauen.
