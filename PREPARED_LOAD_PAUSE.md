# Native Pause nach vorbereitetem Laden

Der Checkpoint-Abgleich darf keinen gemeinsam bereitstehenden Spielzustand
melden, während eine der Instanzen bereits ungebremst weiterläuft. Dieser
Entwurf bindet deshalb eine eigene native Menüpause an die lokal zugelassene
Ladeanforderung und verlangt deren frischen Nachweis bei beiden Vergleichen.
Er baut auf #102 auf und ist im Quellenstand vom 20. November mit #103
integriert. Die Schutzbindung des konkreten Spielstarts ist nun auch für
den Pausenbeleg und den Checkpoint-Abgleich erforderlich. Verlorene oder
gewechselte Belege setzen deren positive Freigabe zurück; eine gehaltene
Pause bleibt erhalten. Das installierte Verbindungstestpaket ist unverändert.

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

Der [Kampagnenstart](SHARED_LOAD.md#lokale-ladeanforderung-für-einen-vorbereiteten-versuch)
gibt die Pause erst mit einem bestätigten Startbefehl und einem passenden
nativen Verbindungsbericht frei. Der Controller beobachtet diese Verbindung
auch während und nach der Rückkehr aus der Pause. Die Diagnose liest den
Bericht einmal pro Sekunde. Fehlt eine Aktualisierung, entscheidet das Alter
des letzten gültigen Berichts. Ein Wechsel der Verbindung oder Mitgliedschaft
entzieht dem bisherigen Versuch sofort bei der nächsten Prüfung den
Kampagnenbeleg.

Hat die native Rückkehr schon begonnen, merkt sich der Controller den
Verbindungsverlust, bis das Menü geschlossen ist. Dann fordert er die Pause
über denselben nativen Menüpfad erneut an. Dazu müssen Ladeanforderung,
Spieler, Szene und Spielfluss weiterhin zum ursprünglichen Versuch passen.
Der Controller wartet bis zu drei Sekunden auf Anforderung und Bestätigung.
Er meldet `interrupted` erst für die bestätigte Pause. Bei einem Wechsel
des Spielkontexts, einem Fehler oder Zeitablauf meldet er `rehold_failed`.
Eine Wiederverbindung oder ein wiederholter Startbefehl hebt diese Pause
nicht auf. Nach einem Abbruch muss der gemeinsame Weltzustand vor einem
erneuten Start abgeglichen werden.

Die Bridge sendet den Freigabebeleg erst, wenn der Controller das Ende
seiner eigenen Pause bestätigt hat. Der Kampagnenbeleg für Posen erscheint
erst mit dem passenden Beleg des Peers. Die Bridge aktualisiert diesen
Beleg nur für neue Nachrichten zur selben Freigabe und Steam-Verbindung.
Fehlt der erste Beleg zehn Sekunden nach dem lokalen Menüende, fordert der
Controller die Pause erneut an. Nach der ersten Bestätigung läuft ein
Beleg nach vier Sekunden ab. Bei beiden Zeitüberschreitungen gilt
`campaign_peer_release_unconfirmed`. RE2 kann vor dem erneuten Anhalten
weiterlaufen. Ändert sich dabei der ursprüngliche Spielkontext, kann die
erneute Pause scheitern. Die gemeinsame Freigabe und die Wiederherstellung
bleiben mit zwei echten Spielinstanzen zu prüfen.

Ein geprüftes Pausenmenü ist außerdem kein vollständiger Weltstillstand.
KI, Physik, Skripte, Cutscenes und laufende Kampfwerte müssen noch erfasst
und auf beiden echten Instanzen verglichen werden. Der Ladekopf bleibt ein
begrenzter Teilzustand und ersetzt keinen vollständigen Welt-Snapshot.

## Nachweise

Am 22. November wurde die erneute Pause im echten Spiel mit einem
simulierten Verbindungsverlust geprüft. Die Schutzdateien der vorhandenen
Installation stimmten mit dem archivierten Testpaket zu #132 überein. Für
den Test wurden zwei abweichende Lobby-Dateien vorübergehend aus der
Startfolge genommen und danach geprüft zurückgestellt.

RE2 lud ausschließlich Slot 4 vom 11.11.2026 und bestätigte zunächst die
native Freigabe. Nach dem simulierten Verbindungsverlust meldete der
Controller `interrupted` und die native Pause `held`. Der bisherige
Kampagnenbeleg erlosch. Drei Messungen der tatsächlichen Spiel-, Rekord-
und Szenenzeit blieben gleich. Zwölf vererbte Lesesperren und die native
Schreibsperre waren aktiv. Die zwölf Originaldateien blieben unverändert,
die eigenen Testskripte wurden entfernt und die Instanz geschlossen.
[Bereinigte Messwerte](validation/native-campaign-rehold-2026-11-22.json)

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

Am 20. November wurde der Controller aus dem integrierten Stand `ebf08e4`
erneut lokal in RE2 geprüft, diesmal mit dem auf diesem Rechner vorhandenen
alten Slot 4 vom 8. April 2026. Die Startbelege aus #103, der zusätzliche
ACL-Schutz und die deaktivierte RE2-Cloud waren gleichzeitig aktiv. Eine
synthetische Beschreibung ohne Peer führte zu drei frischen `held`-Proben
mit nativ bestätigter Pause und durchgehend fehlender gemeinsamer Freigabe.
Als der Starterbeleg absichtlich veraltete, wurde der Schutzstatus ungültig;
die Pause blieb gehalten. Die Simulationsuhren wurden in diesem Lauf nicht
erneut gemessen. [SAVE_PROTECTION.md](SAVE_PROTECTION.md#kombinierter-nativer-einzelinstanz-test-am-20-november-2026)
führt den Dateivergleich, den Plattform-Schreibtest und den geprüften Rückbau
auf. Vorbereitete Zwei-Konten-Zulassung und gemeinsames Fortsetzen bleiben offen.
