# Speicherschutz: Testpaket zurückgezogen

Am 17. November 2026 wurde beim normalen Erreichen eines Checkpoints eine
Autosave-Datei trotz 26 aktiv gemeldeter Lua-Hooks von 3.162.756 auf 540 Bytes
verkürzt. Die beiden gezählten SaveDataManager-Aufrufe und ein aktiver
Hookstatus haben das tatsächliche Schreiben nicht verhindert. Die genaue
Umgehung ist noch nicht isoliert. Manuelle Slotdateien blieben unverändert.

Die eigene Spielinstanz wurde beendet, die lokale Originaldatei aus der zuvor
geprüften Sicherung zurückgespielt und die Testinstallation vollständig
zurückgebaut. Steam hat das Original danach automatisch erfolgreich in die
Cloud hochgeladen; Cloud-Protokoll, Cache-Länge und Cache-Prüfwert stimmen
mit der wiederhergestellten Datei überein. Alle elf lokalen Save-Payloads
entsprechen weiterhin der Originalsicherung. Eine unabhängig heruntergeladene
Cloud-Kopie wurde nicht verglichen. Private Sicherungen, Kennungen und
Protokolle gehören nicht in dieses Repository.

**Das bisherige Paket `RE2-Coop-Test-8c39084` bleibt zurückgezogen.**
Es wurde lokal als `UNSAFE` gekennzeichnet und seine Installations-, Start-
und Ladeaktionen sind gesperrt. Der neue Paketstarter ersetzt diesen
ungeschützten Startpfad. Frühere erfolgreiche Einzelaufrufe des
Lua-Guards belegen keinen vollständigen Dateischutz.

## Native Steam-Sperre als Entwurf

`network/steam_save_guard` baut ein getrenntes Windows-x64-REFramework-Plugin.
Es prüft Prozessname, Steam-App 883710, Build 11636119, die originale
RemoteStorage014-Schnittstelle und die Herkunft ihrer Methoden. Es ersetzt
zehn schreibende Einträge dieser Vtable: FileWrite, FileWriteAsync, FileForget,
FileDelete, FileShare, SetSyncPlatforms und die vier FileWriteStream-Methoden.
Die Ersatzmethoden zählen Aufrufe atomar und liefern den jeweiligen
Fehlschlagswert, ohne den Originalschreiber aufzurufen. FileRead und die
übrigen Einträge bleiben erhalten.

Die [offizielle v014-Definition von Valve](https://github.com/ValveSoftware/Proton/blob/proton_9.0/lsteamclient/steamworks_sdk_151/isteamremotestorage.h)
legt die Slots fest. Die flachen Exporte der vorhandenen Steam-DLL teilen
sich teilweise generische Dispatch-Adressen mit anderen Schnittstellen.
Deshalb werden deren Funktionsadressen nicht global umgebogen.

Der Status `reframework/data/re2_coop_native_save_guard.json` enthält
Prozess-ID, eine Laufkennung, App/Build, Zeit, Integrität und begrenzte Methodenzähler. Der
Bericht wird außerhalb der Ersatzmethoden atomar ersetzt. Er enthält keine
Save-Namen, Inhalte, Spielerkennungen oder Speicheradressen. Er ist kein
Beleg für die Wirkung aller Engine-Schreibpfade. Laufzeit-Entladen und ein
Umschalten des Schutzes während einer Kampagne sind nicht unterstützt.
Ohne die Laufkennung eines geschützten Starts meldet das Plugin keine
Testbereitschaft; seine Steam-Schreibsperren werden trotzdem eingerichtet.

## Unabhängige Windows-Dateisperren

`save_file_guard.SaveFileLocks` öffnet bestehende Dateien mit `GENERIC_READ`
und ausschließlich `FILE_SHARE_READ`. Gemeinsam lesende Zugriffe funktionieren;
neue Schreib-, Lösch- und Ersetzungszugriffe werden vom Betriebssystem
abgewiesen. Bei unvollständigem Erwerb werden alle eigenen Handles freigegeben.
Es werden weder ACLs noch Dateiinhalt oder Steam-Einstellungen geändert.

`retain_in_process` dupliziert die Handles in einen eigenen, noch laufenden
`subprocess.Popen`-Kindprozess mit geprüftem ausführbarem Pfad. Danach bleiben
sie unabhängig vom Hilfsprozess bis zum tatsächlichen Ende dieses Kindes
bestehen. Die Bindung nutzt das ursprüngliche Prozesshandle, keine spätere
PID-Suche. Die Retention kann bei laufendem Kind nicht rückgängig gemacht
werden. Ein Steam-Weiterleitungsprozess darf nicht als Spielprozess dienen.

`spawn` vererbt gezielt duplizierte Handles bereits beim Erzeugen des eigenen
Spielprozesses. So bleibt auch beim Abbruch des Starters vor der ersten
Spielanweisung kein Übergabefenster. Standardhandles werden getrennt, damit
ein Kindprozess keine Konsolen-Pipe des Starters offen hält. Der Starter unter
`tools/test_package` verwendet diesen direkten Pfad und lehnt bereits laufende
Spiele ab. Ein Steam-Weiterleitungsprozess wird nicht als Ersatz akzeptiert.
Die Klasse allein ist kein Testlauncher. Bestehende Schreibhandles,
neue Dateinamen, andere Schnittstellenversionen und andere Prozesse sind durch
die native Vtable-Sperre nicht pauschal abgedeckt. Windows-Sperren verweigern
auch exklusiv lesende Öffnungen; die Kompatibilität des echten Ladevorgangs
muss für jeden unterstützten Build geprüft werden, ohne die Sperren zu lockern.

## Ladefreigabe

Python und Lua verlangen frische, zusammenpassende Berichte der nativen
Steam-Sperre und des Starters mit vererbten Dateisperren. Prozess-ID und
Laufkennung müssen übereinstimmen; die beiden Berichte dürfen höchstens drei
Sekunden alt sein. Der Starter erzeugt vor `CreateProcess` ein eigenes
`protected_launch_token.lua` für die neue Lua-VM und gibt dieselbe Kennung
an das native Plugin weiter. Das Tokenmodul ist keine ausgelieferte Quelle
und wird für jeden Start neu erzeugt. Es hängt nicht von Lua-Umgebungszugriffen ab.

Die Terminalanforderung enthält diese Bindung. Die Lua-Probe verwirft
Anforderungen einer anderen Sitzung vor einem Ladeaufruf. In den Lade-Hooks
werden ausschließlich bereits geprüfte Werte und deren Alter gelesen; keine
zusätzlichen Dateizugriffe finden im Hook statt. Quellenverlust sperrt auch
eine bereits erteilte Slotfreigabe. Die lesende Systemslot-Ausnahme bleibt
erhalten. Die 26 Lua-Hooks allein genügen nicht mehr zum Freigeben einer
Kampagne. Diese lokalen Belege sind keine Authentifizierung gegen manipulierte
Dateien durch andere Programme desselben Benutzers.

## Bestätigte Tests und nächste Abnahme

Acht Windows-Tests mit künstlichen Dateien prüfen Lesen, Trunkierung,
Ersetzen, Löschen, fremden Schreiber, Erwerbsfehler, falsche/abgelaufene
Prozessbindung und die Lebensdauer nach normalem sowie abruptem Ende des
Hilfsprozesses sowie die Vererbung vor der ersten Kindanweisung. Sie verändern
keine RE2-Dateien. Weitere Python-/Lua-Tests prüfen die Ladebindung,
Fristablauf und Quellenverlust. Der Installer wird an künstlichen Ordnern
einschließlich bestehender Modverknüpfungen und fehlgeschlagener Kopie geprüft.
Der native CTest prüft alle zehn
Fehlschlagswerte, unveränderte Leser und ein anderes Interface mit gemeinsamem
Originalzeiger, 4.000 parallele Aufrufe, Integritätsverlust sowie Wiederherstellung
einer tatsächlich schreibgeschützten synthetischen Vtable.

Eine native Einzelinstanz mit RE2 Build 11636119 und REFramework d1461375
bestätigte die neue Steam-Tabelle und anschließend das lesende Laden des
einzigen freigegebenen Slots vom 11.11.2026. Drei frische Spielerproben,
31 gesunde Native-Berichte, genau ein erlaubter Ladeaufruf, null abgefangene
Ladeaufrufe und keine gezählte Speicheranforderung wurden erfasst.
Alle zwölf Dateien blieben unverändert; es kam keine neue hinzu. Die eigene
Instanz wurde geschlossen und Originalmods sowie Konfiguration zurückgestellt.
Der erste Versuch wurde vor einem Load wegen fehlender Lua-Startzuordnung
verweigert; danach wurde ein noch nicht bereites Titelmenü ebenfalls
abgewiesen. Erst die korrigierte Übergabe mit tatsächlich bereitem Menü
bestand. Kein Fehler wurde durch Lockern der Dateisperren umgangen.

Ein absichtlich ausgelöster Autosave-Schreibpfad mit echten Dateien wurde
damit **nicht** abgenommen. Die anschließende Paketprüfung mit Lobbyplugin
und portablem Python bestand für einen Host mit privater Lobby und altem
Load sowie einen getrennten Gaststart ohne Einladung. Nach beiden Läufen
blieben zwölf Dateien unverändert. Ein kurz überlappender Lua-Leser ließ den
ersten Starter beim atomaren Status-Ersetzen abbrechen; der Starter verwendet
jetzt den bereits vorhandenen begrenzt wiederholenden Writer. Zwei zusätzliche
Windows-Tests prüfen die Erholung nach kurzem Lesen und den sicheren Abbruch
bei dauerhafter Sperre. [TEST_PACKAGE.md](TEST_PACKAGE.md) hält die Paketprüfung
fest. Die Verbindung zweier echter Konten bleibt offen; beide PCs benötigen
dieselbe neue Fassung.

Diese Abnahme ersetzt weiterhin keine synchronisierte Koop-Kampagne.

## Build und isolierte Prüfung

Mit den in CI gepinnten REFramework-Headern und Visual Studio x64:

```powershell
cmake -S network/steam_save_guard -B staging/save-guard-build -A x64 "-DREFRAMEWORK_INCLUDE_DIR=C:/path/to/REFramework/include"
cmake --build staging/save-guard-build --config Release
ctest --test-dir staging/save-guard-build -C Release --output-on-failure
python -m unittest tests.test_save_file_guard -v
```

Der Build allein installiert nichts. `tools/test_package/build_package.py`
erstellt mit `--output`, `--python-archive` und `--sdk-root` ein getrenntes
Testverzeichnis aus Git-Quellen, beiden eigenen DLLs und dem fest geprüften
Python-Originalarchiv. `ZUERST_LESEN.md` beschreibt den begrenzten Raumtest.
Eine gemeinsame Koop-Kampagne ist weiterhin nicht freigegeben.
