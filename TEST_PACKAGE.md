# Geschütztes Testpaket

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

#93–#102 sind getrennte Entwicklungszweige und keine Bestandteile dieser
Paketfassung. #95/#100–#102 verwenden unter anderem ACL-Schutz, Cloud-Prüfung,
aktive Steam-Savepfade und vorbereitete gemeinsame Checkpoints. #103 verwendet
vererbte Handles, eine native RemoteStorage-Vtable-Sperre und an den Start
gebundene Ladebelege. Diese unterschiedlichen Schutz- und Anforderungsformate
müssen vor einer Zusammenführung bewusst abgeglichen werden. Keiner der
PRs wurde durch die Paketprüfung nach `main` gemergt.

Der nächste Nutzertest braucht auf beiden PCs exakt dasselbe Paket und
einen abgesicherten eigenen Save im selben Raum. Ohne passenden freigegebenen
Save bleibt der Lobbytest möglich. Für normalen Kampagnenfortschritt zuerst
RE2 schließen und die Testinstallation über `Entfernen.cmd` zurückbauen.
