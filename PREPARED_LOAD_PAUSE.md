# Native Pause nach vorbereitetem Laden

Der Checkpoint-Abgleich darf keinen gemeinsam bereitstehenden Spielzustand
melden, während eine der Instanzen bereits ungebremst weiterläuft. Dieser
Entwurf bindet deshalb eine eigene native Menüpause an die lokal zugelassene
Ladeanforderung und verlangt deren frischen Nachweis bei beiden Vergleichen.
Er baut auf #102 auf und ändert das installierte Verbindungstestpaket nicht.

## Ablauf

`re2_coop/prepared_load_pause.lua` übernimmt ausschließlich eine zuvor
geprüfte Anforderung des vorbereiteten Steam-Lobbyversuchs. Vor dem nativen
Load wird die Pause reserviert; scheitert schon der Load-Aufruf, kann diese
noch nicht aktive Reservierung zurückgenommen werden. Nach Beginn des
Szenenwechsels versucht der Controller die vorhandene native Pause, sobald
deren eigene Spielbereitschaftsprüfung es zulässt. Die gespeicherte
Lade-ID ist gleichzeitig die eigene Pause-ID.

Die Pausenprimitive wird beim Skriptstart geladen und an den Controller
übergeben. Im nativen Update-Callback wird kein Modul nachgeladen. Das
Pausenobjekt wird pro Update geprüft; der Lobby-JSON wird höchstens einmal
pro Sekunde eingelesen. Die Diagnose-Hooks bekommen dadurch keine neuen
Dateizugriffe oder Spiel-Getter.

Ein `load_hold` ist erst verfügbar, wenn der richtige Load `scene_loaded`
erreicht hat, die eigene Pause nativ `held` und verifiziert ist und der
ursprüngliche Lobbyversuch weiterhin passt. Prozess, Rolle, Mitgliedschaft,
Sitzung, Versuch, Revision, Save-Digest und Referenz bleiben gebunden.
Ein erwarteter Katalogausfall nach dem zugelassenen Load darf dieselbe
Bindung behalten; ein anderer Versuch oder eine andere Mitgliedschaft nicht.

Wenn die Gegenstelle oder der Loadbeleg ausfällt, bleibt eine schon eigene
Pause erhalten. Der Controller versucht auch bei fehlender Gegenstelle den
lokal fertig geladenen Zustand anzuhalten. Er übernimmt keine fremde Pause
und setzt den Spielablauf weder nach Zeitablauf noch nach Quellenverlust
selbstständig fort. Eine gehaltene Anforderung kann nicht durch einen
neuen Arm-/Loadbefehl ersetzt werden.

Der vorbereitete Terminal-Load wartet nach `scene_loaded` zusätzlich auf
diese Pause. Fehlende oder fremde Pause-IDs melden keinen Erfolg; ein
verlorenes Pausenobjekt ergibt einen Fehler. Einzelne Legacy-Leseproben
werden dadurch nicht in gemeinsam vorbereitete Loads umgedeutet.

Die Option `--prepared-lobby` legt diese Wartebedingung bereits im Terminal
fest. Auch wenn der native Status das Feld `prepared_load` auslässt, wartet
der Befehl auf den frischen Pausennachweis zur eigenen Lade-ID. Läuft seine
Frist ab, meldet er `waiting_for_native_pause`.

## Checkpoint und Grenzen

`PreparedCheckpoint` liest die passende Pause vor und nach dem nativen
Ladekopf. Der bestätigte Snapshot verwendet dafür Unterformat 2 mit
`native_pause_held=true`. Beide Phasen des bestehenden Transfers prüfen
weiterhin denselben Peer und dasselbe Checkpoint-Digest. Endet die Gastpause
nach der ersten Bestätigung, schlägt die endgültige Bestätigung fehl.
Ältere Checkpoint-Clients werden nicht stillschweigend akzeptiert.

**Eine vollständige gemeinsame Spielfreigabe fehlt weiterhin.** Dieser
Controller hat bewusst noch keinen automatischen Rückkehrpfad. In diesem
Entwurf endet ein kontrollierter Test mit dem Schließen der Testinstanzen.
Manuelles Fortsetzen beendet den eigenen Pausennachweis und erlaubt keinen
positiven Checkpoint-Abgleich mehr. Die verteilte Freigabe braucht eine
eigene abgestimmte Phase; ein lokaler Timeout darf sie nicht ersetzen.

Ein geprüftes Pausenmenü ist außerdem kein vollständiger Weltstillstand.
KI, Physik, Skripte, Cutscenes und laufende Kampfwerte müssen noch erfasst
und auf beiden echten Instanzen verglichen werden. Der Ladekopf bleibt ein
begrenzter Teilzustand und ersetzt keinen vollständigen Welt-Snapshot.

## Nachweise

Lua-Tests prüfen die frühe Pausenanforderung, bestätigte Szenenbereitschaft,
Katalogausfall, verlorene Mitgliedschaft, veraltete Zustände, geänderte
Policy, native Fehler, fremde/abgelöste Pause und kopierte Bindungsdaten.
Die aktualisierte Skriptprobe wird auf Update-Takt, Abbruch vor einem
Load ohne Pausenprimitive und Ablehnung weiterer Befehle während der
eigenen Pause geprüft. Python-Tests prüfen unter anderem einen Verlust
während des Lesens und nach der ersten Peer-Bestätigung.

Ein zusätzlicher nativer Einzelinstanz-Versuch am 17. November 2026 nutzte
RE2 Build 11636119, REFramework d1461375 und ausschließlich den freigegebenen
alten Slot 4 vom 11.11.2026. Er lief unter der bestehenden Schutzfassung
`4494ef2` mit vererbten Dateisperren und nativer Steam-Schreibsperre.
Die neue Komponente erhielt eine ausdrücklich **synthetische Beschreibung
ohne Gegenstelle**, gebunden an die echte lokale Lade-ID. Das prüft den
lokalen Pausenpfad bei fehlendem Peer; es ist keine vorbereitete gemeinsame
Ladeabnahme und wird nicht als solche ausgegeben.

Der echte Pausenpfad erreichte `held`. Über drei frische Proben blieben
tatsächliche Spielzeit, Rekordzeit und Szenenzeit gleich. Systemzeit, rohe
Spielzeit und Pausenzeit liefen weiter, wie bereits in
[GAMEPLAY_PAUSE.md](GAMEPLAY_PAUSE.md) dokumentiert. Der Controller gab
erwartungsgemäß **keinen** gemeinsamen Checkpoint frei. Es gab einen
erlaubten Load, null verweigerte Loads und keine gezählte Speicheranforderung.
Alle zwölf Dateien blieben bytegleich, keine neue Save-Datei erschien.
Nur die eigene Instanz wurde geschlossen; temporäre Diagnoseskripte,
Laufkennung und Konfiguration wurden zurückgestellt.

Die Abnahme bezieht sich auf die dokumentierte Dreiergruppe der
Simulationsuhren; System- und rohe Spielzeit gelten ausdrücklich als
weiterlaufend. Private Rohberichte werden nicht veröffentlicht. Zwei echte
Steam-Konten und ein automatischer gemeinsamer Start sind weiterhin nicht
nachgewiesen.
