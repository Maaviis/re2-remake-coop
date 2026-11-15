# Nativer Gameplay-Pausenbaustein

Die gemeinsame Ladebarriere braucht einen nachweislich ruhenden Zustand,
bevor Werte verglichen und angewandt werden. Ein früherer Test zeigte:
`Scene.TimeScale=0.0` hielt den beobachteten Idle-Clip an, während die
erfassten GameClock-Zähler weiterliefen. Dieser Baustein verwendet den
tatsächlichen Gameplay-Pausenablauf des Spiels.

Er ist ein getesteter lokaler Baustein für RE2 Build 11636119,
REFramework d1461375 und TDB 70. Vollständiger Weltstillstand, Cutscene-Pause,
Netzwerkkoordination und Freigabe beider Spielinstanzen sind weiterhin offen.

## Nativer Ablauf

`re2_coop/gameplay_pause.lua` prüft die verwendeten Methodensignaturen,
den Pausenzustandstyp und dessen bestätigten `UPDATE`-Wert. Es setzt keine
Spielfelder, verändert keinen Zeitfaktor und ruft keine Speicherfunktion auf.

1. Eine neue zufällige ID fordert über `MainFlowManager.goPause()` die
   Gameplay-Pause an. Titelbild, Laden, beschäftigter Save-Manager,
   bestehende Pause oder geöffnetes Pausenmenü werden abgewiesen.
2. Das Modul hält die Identität von MainFlow, Szene und aktuellem Spieler
   fest. Es wartet auf den nativen Pause-Flow, dessen `UPDATE`-Zustand,
   geöffnetes Menü und genau eine passende, eingabebereite
   `app.ropeway.gui.PauseBehavior`-Komponente in der aktuellen Szene.
   Erst dann gilt die lokale Phase `held` als verifiziert.
3. Eine Rückkehr benötigt dieselbe ID und erneut bestätigte Objektidentität.
   Das Modul ruft `PauseBehavior.toReturnGame()` auf. Dadurch übernimmt
   die native Menüaktion das Schließen der Oberfläche und die Übergabe
   ihres RETURN-Ergebnisses an den Spielablauf.
4. `released` wird erst bestätigt, wenn Pause-Flow und Menü geschlossen
   sind und `get_IsInGameNotPause()` wieder wahr ist.

Ein direkter Aufruf des Ergebnis-Callbacks am Pause-Flow reichte im ersten
nativen Versuch nicht aus: Der Flow wechselte ins Spiel, während
`GUIMaster.get_IsOpenPause()` wahr blieb. Diese Abkürzung ist nicht Teil
des Moduls. Der bestätigte Rückweg läuft über die echte Menüaktion.

Überlappende Anforderungen ersetzen keine aktive ID. Wiederverwendete IDs
werden verworfen. Spieler-, Szenen-, Flow- oder Menüobjektwechsel verwerfen
die bestätigte Zuordnung; das Modul nimmt dann keine fremde Pause zurück.
Fehlende oder ungültige Abfragen liefern keine verifizierte Pause aus
früheren guten Werten. Das ist eine Zuordnung innerhalb dieses lokalen
Controllers, noch keine an Steam-Teilnehmer und Link-Epoche gebundene
verteilte Besitzregel.

## Begrenzte Terminalprobe

Zusätzlich zum Modul wird die ausdrücklich aktivierte Diagnose
`reframework/diagnostics/re2_coop_gameplay_pause_probe.lua` in einer
isolierten Entwicklerinstallation als Autorun installiert. Sie benötigt
die vorhandene Guard-/Ladeprobe, den Katalog und den Detailbeobachter aus
[READONLY_LOAD.md](READONLY_LOAD.md) und [INVENTORY_WITNESS.md](INVENTORY_WITNESS.md).

Die Diagnose veröffentlicht `reframework/data/re2_coop_gameplay_pause.json`.
Ihr Umfang heißt `native_gameplay_pause`. Eine Pausenanforderung muss an
die aktuelle native Lade-ID und aktive Policy gebunden sein; der Guard
muss frisch sein, alle 26 Hooks melden und darf kein abgefangenes Laden
oder Schreiben zeigen. Der Terminalclient prüft zusätzlich den erlaubten
Katalogtermin und die frischen Inventar-Detailwerte für genau diese Lade-ID.
Damit wird ausschließlich die bereits geladene Instanz pausiert; die
Probe lädt keine Kampagne und schreibt keinen Spielstand.

```powershell
python gameplay_pause_control.py --data "<RE2>/reframework/data" status
# Zuvor den erlaubten alten Slot mit readonly_save_control.py laden.
# Die dabei bestätigte eigene native Lade-ID einsetzen:
python gameplay_pause_control.py --data "<RE2>/reframework/data" pause --load-id "<native Lade-ID>" --allow-save-date 2026-11-11 --seconds 10 --wait 5
# Die ausgegebene pause_id einsetzen:
python gameplay_pause_control.py --data "<RE2>/reframework/data" return --pause-id "<eigene Pause-ID>" --wait 5
```

Die lokale Diagnose begrenzt eine Pause auf 2 bis 15 Sekunden und fordert
danach über denselben geprüften Menüpfad die Rückkehr an. Zeitrücksprünge
lösen ebenfalls einen Bereinigungsversuch aus. Diese Frist ist eine
Testbereinigung und verwendet die lokale Kalenderuhr. Sie ist ausdrücklich
keine Regel für einen Verbindungsabbruch im späteren Koop: Der Koordinator
muss beide Welten bis zur sicheren Zustandsübernahme kontrollieren.
Das Kernmodul selbst löst keine automatische Rückkehr nach Netzverlust aus.

Die Befehls-ID, die aktive Pause-ID und die ID einer akzeptierten Rückkehr
sind getrennt. Ein anderer abgewiesener Befehl überschreibt keinen aktiven
Pausenvorgang. `--wait` bestätigt die eigene verifizierte Pause beziehungsweise
die eigene abgeschlossene Rückkehr. Eine automatische Rückkehr trägt
`release_id:deadline`. Alte Statusdateien, falsche Umfänge und ungültige
UInt64-Uhrenwerte werden abgewiesen. Die Uhren stehen als Dezimalstrings
in JSON und werden nicht durch einen Gleitkomma-Digest ersetzt.

## Nachweise und Grenzen

141 Python-Tests und zwölf Lua-Suiten bestehen lokal. Sie prüfen unter
anderem unterstützte Signaturen, bestehende/fremde Pausen, wiederverwendete
IDs, Objektwechsel, verzögerte Menüabschlüsse, Quellenverlust, getrennte
Ergebnisse überlappender Befehle, Guard-/Lade-ID-Bindung, Kalenderfilter,
Fristablauf und die Bereinigung einer bereits gehaltenen Pause bei Reset.

Die native Voruntersuchung bestätigte zwei Pause-/Rückkehrzyklen in einer
Instanz, einen über einen expliziten Befehl und einen nach Zeitablauf.
Während der Pause blieben tatsächliche Spielzeit, Rekordzeit, Szenenzeit
und der beobachtete Claire-Idle-Animationsframe gleich. Systemzeit und
rohe Spielzeit liefen weiter; die native Pausenzeit wuchs entsprechend.
Nach der Rückkehr stiegen die tatsächlichen Spiel-/Szenenzeiten und die
Animationsframes wieder. Der Bildschirminhalt und physische Eingaben
wurden dabei nicht abgenommen.

Eine anschließende frische Abnahme verwendete das fertige Modul, die neue
Diagnose und die öffentlichen Terminalbefehle. Die explizit gehaltene
Pause ergab 28 frische Proben, die zeitlich begrenzte Pause 14: jeweils
unveränderte tatsächliche Spielzeit, Rekordzeit, Szenenzeit und Animation.
Vorher und nachher stiegen die Werte. Eine weitere Pausenanforderung und
eine Rückkehr mit fremder ID wurden nativ abgewiesen, ohne die aktive
Pause oder deren ursprüngliches Ergebnis zu ersetzen. Beide Rückkehrwege
erreichten `released` über den vollständigen nativen Menüabschluss.

Alle Läufe verwendeten ausschließlich den erlaubten alten Slot vom
11.11.2026. Im Abnahmelauf gab es genau eine erlaubte Leseanforderung,
null abgefangene Ladeanforderungen und keinen Speicheraufruf. Es gab keine
Tastatur-/Mauseingabe, keinen Fokuswechsel und keine Bildschirmaufnahme.
Nach Ende ausschließlich des eigenen Testprozesses wurden Originaldateien
zurückgestellt; alle zwölf Save-Dateien waren unverändert, keine neue
erschien. Private Messwerte und Installationspfade bleiben lokal.

Offen bleiben Gegner-/KI-/Physik- und Skriptverhalten während der Pause,
alle Cutscenes, Menüs in anderen Kampagnenzuständen, Benutzereingriffe,
Reset während des noch anlaufenden Menüs sowie native Ausnahme-/Absturzpfade.
Eine nicht verifizierbare Pause darf kein vollständiges Weltabbild oder
eine Freigabe bestätigen. Der spätere Koordinator muss zusätzlich Prozess,
Steam-Sitzung und Link-Epoche, globalen Ladeversuch, vollständigen Zustand
und Wiederverbindung binden. Sämtliche Zwei-Instanzen-Nachweise bleiben
erforderlich; dieser Baustein ersetzt sie nicht.
