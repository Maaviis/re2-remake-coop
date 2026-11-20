# RE2 Coop – geschützter Verbindungstest

Dieses Entwicklungspaket prüft Steam-Lobby, Einladung und die Übertragung
von Position und Blickrichtung. Die Gegenstelle kann einen Marker im Raum
sehen. **Eine gemeinsame Koop-Kampagne mit zwei steuerbaren Charakteren ist
noch nicht spielbar.** Gegner, Items, Fortschritt und Cutscenes sind nicht
vollständig synchronisiert.

Das alte Paket `RE2-Coop-Test-8c39084` ist wegen eines nachgewiesenen
Save-Schutzfehlers zurückgezogen. Nur die neue Fassung mit beiden DLLs und
geschütztem Starter verwenden. [SAVE_PROTECTION.md](SAVE_PROTECTION.md)
beschreibt Befund, neue Sperren und die Grenzen der bisherigen Abnahme.

## Voraussetzungen auf beiden PCs

- Eigene Steam-Konten, eigene RE2-Kopien, Steam online und Overlay für RE2 aktiv.
- Windows x64, getesteter RE2-RT-Build 11636119 und REFramework d1461375/TDB 70.
  REFramework muss bereits installiert sein; dieses Paket enthält keine
  Spielressourcen, Steam-DLLs oder fremden Mods.
- Dasselbe neue Paket auf beiden PCs. Python ist portabel enthalten.
- Für den Posentest: jeweils ein eigener freigegebener Szenario-Save im
  selben Raum. Das Datum wird bei der Installation festgelegt; Vorgabe ist
  **11.11.2026**. Ohne passenden Save zunächst nur die Lobby testen.
  Keine fremden Steam-Speicherdateien kopieren.

## Installieren

1. ZIP vollständig in einen beschreibbaren Ordner entpacken und RE2 schließen.
2. `Installieren.cmd` öffnen. Bei mehreren Installationen mit
   `--game "D:\SteamLibrary\steamapps\common\RESIDENT EVIL 2  BIOHAZARD RE2"`
   den richtigen Ordner angeben.
   Ein anderes ausdrücklich freigegebenes lokales Datum wird beim Installieren
   angegeben, zum Beispiel `Installieren.cmd --allow-save-date 2026-04-08`.
   Der Installer meldet und speichert das Datum. Lobby und Ladeprogramm
   verwenden anschließend diese Auswahl; zum Ändern zuerst RE2 schließen,
   `Entfernen.cmd` ausführen und neu installieren. Die Paketdateien bleiben
   auf beiden PCs gleich, die Freigabe gehört zur jeweiligen Installation.
3. Der Installer sichert Saves mit Prüfsummen und verschiebt die bisherigen
   REFramework-Ordner `autorun`, `plugins` und `data` unverändert in
   `re2-coop-backup-...` neben `re2.exe`. Vortex-Quellen bleiben erhalten.
4. Während der Testinstallation keine Mods über Vortex neu bereitstellen
   und RE2 ausschließlich mit dem Host-/Gaststarter dieses Pakets öffnen.
   Eine aktive oder unbekannte Installation wird nicht überschrieben.
   Eine zuvor vollständig zurückgebaute Testinstallation wird bei erneutem
   Installieren als `previous-installation` im neuen Sicherungsordner erhalten.
   Dafür muss ihr abgeschlossener Rückbau ausdrücklich bestätigt sein;
   ein nach Abbruch lediglich inaktiver Zustand genügt nicht.

Der Starter prüft Paket, Original-Saves und Sicherung vor dem Spielstart.
Er vererbt Windows-Lesesperren bereits beim Erzeugen des RE2-Prozesses.
Zusätzlich blockiert das native Plugin schreibende Steam-Aufrufe. Die
Lua-Ladefreigabe verlangt frische Belege für beide Schutzschichten derselben
Instanz. Eine Meldung „26 Hooks aktiv“ allein reicht nicht.

## Lobby testen

1. Bei geschlossenem RE2 auf PC 1 `Host-starten.cmd`, auf PC 2
   `Gast-starten.cmd` öffnen. Steam muss bereits laufen. Die Starter öffnen
   jeweils eine eigene geschützte RE2-Instanz; eine bereits laufende Instanz
   wird nicht übernommen. Konsolenfenster während des Tests offen lassen.
2. Im Hauptmenü **Multiplayer** öffnen; alternativ öffnet/schließt F9 die
   Lobby. Das REFramework-Debugmenü lässt sich mit Einfg/Insert schließen.
3. Host: private Steam-Lobby erstellen und den vereinbarten Mitspieler
   über den Steam-Einladungsdialog auswählen.
4. Gast: Steam-Einladung öffnen und in Multiplayer annehmen. Beide
   geschützten Starter müssen bereits laufen.
5. `Teststatus.cmd` auf beiden PCs öffnen. Erwartet: `save_protection.active`
   und `save_guard.protection_active` sind `true`, Host `steam_lobby: owned`,
   Gast `joined`, bei bestehender Verbindung `lobby.connected: true`.

Ein wartender Host allein bestätigt keine Zwei-Spieler-Verbindung.

## Position und Richtung testen

1. Auf beiden PCs `Spielstand-laden.cmd` öffnen. Vorgabe ist `scenario:4`;
   `--slot scenario:NUMMER` wählt einen anderen eigenen Slot desselben
   erlaubten Datums. Die lokale Installation kann zusätzlich exakt an
   ihren vorher freigegebenen Slot 4 gebunden sein.
2. Das Ladeprogramm wartet auf das bereite Originalmenü und meldet Erfolg
   erst nach dem nativen Szenenbeleg. Die beiden Kampagnen starten dadurch
   noch nicht gemeinsam; die Lobby-Auswahl allein lädt keinen Save.
3. Im selben Testraum bleiben, nacheinander bewegen und drehen. Die
   Gegenstelle prüft Marker und Richtung. Das ist ein Darstellungs- und
   Transporttest, kein zweiter spielbarer Charakter. Keine Checkpoints,
   Kämpfe, Raumwechsel oder Storyfortschritte für diese Abnahme verwenden.
4. Gast die Lobby verlassen lassen. Der Marker muss nach dem Ablauf seiner
   Empfangsfrist verschwinden. Wiederbeitritt getrennt prüfen.

Keine normale Fortsetzen-/Laden-Aktion verwenden und keinen Fortschritt
speichern. Bei einem abgewiesenen nativen Ladeversuch RE2 und Bridge neu
starten. Ein Bridge-Neustart erfordert in dieser Fassung einen neuen
geschützten Spielstart. Das Paket führt keine globalen Tastatur- oder
Mausaktionen aus.

## Vorbereiteter gemeinsamer Ladeversuch

Für diesen Entwicklertest auf beiden PCs eine isolierte Kopie am aktiven
Steam-Savepfad vorbereiten und RE2-Cloud vorher ausschalten. Der mitgelieferte
`scripts/protect_re2_test_saves.ps1` läuft in PowerShell 7 (`pwsh`) und
schützt die Kopie vom Start bis zum Ende des Spiels. [READONLY_LOAD.md](READONLY_LOAD.md)
beschreibt den Windows-Schutz und die Wiederherstellung. Der Starter prüft
den aktiven Pfad in RE2, den laufenden Schutz und den Cloud-Status.

Host und Gast übergeben mit `--prepared-save-directory` den absoluten Pfad
ihrer geschützten Kopie. Im entpackten Paketordner kann der Host folgenden
Block ausführen. Der Gast setzt `Gast-starten.cmd` ein.

```powershell
.\scripts\protect_re2_test_saves.ps1 -SaveDirectory $testSaveDirectory -WhileProtected {
    .\Host-starten.cmd --prepared-save-directory "$testSaveDirectory"
    while (Get-Process -Name re2 -ErrorAction SilentlyContinue) {
        Start-Sleep -Seconds 1
    }
}
```

Nach bestätigter Verbindung und übereinstimmender Save-Auswahl melden sich
beide bereit. Der Host stößt die Prüfung über
`runtime\python.exe lobby_control.py --data "$re2DataDirectory" check-load`
an. Bei `load_check.phase=prepared` verwendet `Spielstand-laden.cmd` mit dem
vereinbarten `--slot` den vorbereiteten Pfad aus dem laufenden Starter. Der
Befehl wartet auf die eigene native Pause. Ohne gültigen gemeinsamen Versuch
bleibt der Load gesperrt. Die Testinstanzen schließen, bevor der ACL-Block
endet. Gemeinsames Fortsetzen ist noch offen.

## Beenden und wieder normal spielen

1. Steam-Lobby verlassen, dann `Test-beenden.cmd` oder Strg+C im Bridgefenster.
2. RE2 schließen. Die vererbten Dateisperren bleiben auch nach dem Ende der
   Bridge bis zum tatsächlichen Spielende bestehen.
3. `Entfernen.cmd` öffnen. Erst nach dem Rückbau wieder die eigenen
   Kampagnen regulär spielen und speichern. Originalmods und Konfiguration
   werden zurückgestellt; Saves werden nie automatisch zurückkopiert.

Bei einer veränderten Datei oder Schutzmeldung abbrechen und den kurzen
Teststatus sichern. Private Sicherungen und Diagnoseordner enthalten
persönliche Daten; sie gehören nicht in das weitergebbare ZIP.

## Herkunft

- Eigenständiger Projektcode: [Maaviis/re2-remake-coop](https://github.com/Maaviis/re2-remake-coop),
  MIT-Lizenz. Der genaue Quellcommit und Dateihashes stehen in
  `bundle-manifest.json`.
- Beide nativen Plugins werden aus diesem Quellstand gebaut.
- [Python 3.13.17 Windows embeddable x64](https://www.python.org/downloads/release/python-31317/),
  Originalarchiv-SHA-256
  `9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38`;
  Lizenz unter `runtime/LICENSE.txt`. Header-Lizenzen unter `third-party`.
