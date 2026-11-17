# Kontrollierte native Ladeprobe

Dieser Entwurf ergänzt den Katalog aus #45 und die Eingabe aus #46 um
eine ausdrücklich aktivierte Entwicklerprobe. Er ist kein gemeinsamer
Kampagnenstart. Die normalen Lobby-Skripte laden oder speichern dadurch
weiterhin keinen Spielstand.

Ein regulärer Checkpoint hat in [#91](https://github.com/Maaviis/re2-remake-coop/pull/91)
`data000.bin` trotz aktiver Lua-Hooks verändert. Die Kampagnentests benötigen
zusätzlichen Schutz im Dateisystem. Der nächste Abnahmeschritt ist ein
echter Checkpoint mit vollständig isolierten Testdateien.

Vor der Wahl der Testumgebung die aktuelle Steam-Cloud-Einstellung im
RE2-Hauptmenü abfragen. Die Abfrage verwendet den Client-Kontext des Spiels.

~~~powershell
.\network\steam_lobby_probe\lobby.ps1 -Command cloud-status
~~~

Für einen Lauf mit einer lokalen Testkopie müssen Steam Cloud für RE2
deaktiviert und das reguläre Save-Verzeichnis unabhängig gesichert sein.
Bei `cloud-enabled` oder `cloud-unavailable` zuerst die Cloud-Einstellung
im Steam-Client prüfen.

Für `--prepared-lobby` verwendet der Ladebefehl den lokalen Steam-
Benutzerdatenpfad aus dem Prozess und leitet daraus das aktive
`remote/win64_save` von RE2 ab. Die geschützte Kopie muss an dieser Stelle
liegen. Der Befehl vergleicht die Verzeichnisidentität vor und nach dem
Lesen, selbst wenn die Dateien einer anderen Kopie dieselben Bytes haben.
Vor dem Einreichen des Ladebefehls muss das Plugin `cloud-app-disabled`
oder `cloud-account-disabled` melden. Das Verzeichnis und seine
Berechtigungen wie unten beschrieben vorbereiten. Die native Abfrage
verwendet das in diesem Build verfügbare `GetUserDataFolder`. [Steamworks-Dokumentation](https://partner.steamgames.com/doc/api/ISteamUser#GetUserDataFolder)

## Windows-Dateisystemschutz im Testverzeichnis

`scripts/protect_re2_test_saves.ps1` öffnet die vorhandenen Dateien lesend
und sperrt Schreibzugriffe, Ersetzungen und neue Dateien zusätzlich über
NTFS-Berechtigungen. Eine temporäre Regel am direkten Elternordner sperrt
auch das Umbenennen des geschützten Ordners. Der Schutz wird zusammen mit
einem lokalen Wiederherstellungsprotokoll eingerichtet, bevor der angegebene
Block läuft. Ein normaler Abschluss oder eine Ausnahme setzt die vorherigen
Berechtigungen zurück.

Der vorbereitete Ladebefehl prüft zusätzlich den laufenden Wrapper.
Dieser veröffentlicht seinen lokalen Nachweis erst nach dem Einrichten
aller Sperren. Windows entfernt den Nachweis beim Schließen des Wrappers
auch nach einem Prozessabbruch. Nach einem Prozessabbruch bleiben die
Berechtigungssperren und ihr separates Wiederherstellungsprotokoll bis
zur Wiederherstellung bestehen. Der Check verlangt den geöffneten Nachweis
des laufenden Wrappers. Der geschützte Block muss bis zum Ende des
RE2-Testprozesses laufen.

Die Regression läuft ausschließlich mit erzeugten Testdateien. Sie prüft
Lesbarkeit, verweigerten Zugriff aus einem zweiten Prozess und manuelle
Wiederherstellung nach abruptem Prozessende.

~~~powershell
pwsh -NoProfile -File tests/test_save_storage_guard.ps1
~~~

Für einen eigenen Versuch einen separaten lokalen NTFS-Ordner `win64_save`
mit Testdateien auswählen. Bei abruptem Prozessende bleiben die Sperren
aktiv. Nach Ende aller Testprozesse stellt `-Restore` für denselben Ordner
die alten Berechtigungen aus `%LOCALAPPDATA%\RE2Coop\save-guard` wieder her.

~~~powershell
.\scripts\protect_re2_test_saves.ps1 -SaveDirectory $testSaveDirectory -Restore
~~~

## Nativer Lade- und Schreibtest am 17. November 2026

Mit RE2 Steam-Build 11636119, REFramework d1461375 und TDB 70 wurde eine
Kopie der aktiven Steam-Datenablage geschützt geladen. Der geprüfte
Quellstand war `8a1a60b`. Ein lokaler Plugin-Testbuild ergänzte Befehle für
die ausdrücklich freigegebene vorübergehende Cloud-Änderung und den
kontrollierten Aufruf von `ISteamRemoteStorage::FileWrite`.

Der aktuelle lokale Katalog lieferte Slot 4 mit dem Kalenderdatum
8. April 2026. Für diese Kopie erreichte genau eine native Ladeanforderung
`scene_loaded`. Fünf frische Ladekopf-/Inventarproben und eine verfügbare
Spielerpose wurden geprüft. Der Guard meldete null abgewiesene
Ladeanforderungen und null abgefangene Speicheraufrufe.

Der anschließende native Plattformaufruf zum Überschreiben der kopierten
`data000.bin` meldete einen abgewiesenen Schreibzugriff. Alle 23
Speicherdateien der Kopie waren auch nach Spielende und Rücknahme der
Sperren bytegleich. Danach wurden die Originalablage, REFramework,
Konfiguration und die zuvor aktivierte Steam Cloud wiederhergestellt.
Die 24 Dateien der originalen Steam-Ablage und 31 REFramework-Dateien
stimmten mit ihren vorher erfassten Prüfsummen überein.

Der erste Lauf endete beim Warten auf die Titelbereitschaft. Der erneute
Lauf verwendete das aktuelle Katalogdatum und wartete auf den tatsächlichen
Titelzustand. Beide Läufe stellten die ursprüngliche Umgebung wieder her.
Ein gewöhnlicher Kampagnen-Checkpoint und der gemeinsame Lauf mit zwei
Steam-Konten stehen weiterhin aus.

## Installation und Bedienung der Probe

Die Module `reframework/autorun/re2_coop/save_guard.lua` und
`readonly_loader.lua` werden erst durch `require` aktiv. Nur für einen
isolierten Test wird zusätzlich
`reframework/diagnostics/re2_coop_readonly_save_probe.lua` ins
Autorun-Verzeichnis kopiert. **Diese Diagnose deaktiviert die von ihr
abgefangenen Speicher- und Löschaufrufe.** Sie gehört nicht in eine
Installation, mit der normaler Spielfortschritt gespeichert werden soll.
Vor einem Test vollständige Sicherungen verwenden; danach die
Testinstallation entfernen und die Originaldateien zurückstellen.

Der native Katalogexporter und Observer müssen ebenfalls laufen.
Aus dem Projektverzeichnis kann eine datumsgefilterte Referenz freigegeben
werden, ohne einen Ladevorgang anzufordern:

```powershell
python readonly_save_control.py --data "<RE2>/reframework/data" --allow-save-date 2026-11-11 scenario:4
```

Nur mit dem zusätzlichen Argument `--load` wird das native Lesen dieses
Slots angefordert. Das ist eine lokale Entwickleranweisung, keine
Netzwerknachricht und kein Startknopf der Lobby. Die CLI verlangt einen
frischen Guard-Status mit vollständiger Hook-Konfiguration und einen
frischen, zum Datum passenden Katalogeintrag. Der native Guard prüft
Slot, Szenario und Zeitwert erneut an der vorhandenen Engine-Tabelle.
Der Metadatenverweis bestätigt nicht den Inhalt der Speicherdatei.

Die lokale Datei `re2_coop_save_guard.json` meldet die angenommene
Policy-ID, abgefangene Aufrufe, Ladephase, Fehler und die abgefragten
Titel-/Haupt-/Kampagnen-/Ladedialog-Zustände. Bei fehlendem GUIMaster
steht `gui_available=false`; dessen Zustände werden dann nicht als
geschlossen ausgegeben. Die Zahl `hooks`
zählt konfigurierte Hooks; sie ersetzt keine Bestätigung der Installation
im REFramework-Log. `allowed_load_calls` zählt erlaubte Aufrufe, keine
erfolgreich abgeschlossenen Ladevorgänge.

Die begrenzte JSON-Spur `trace` erfasst höchstens 64 Ein- und Austritte
der Ladefunktionen. Auch diese Diagnose-Hooks führen keine zusätzlichen
Spielabfragen aus und lassen Originalaufrufe sowie Rückgabewerte
unverändert. Ein Ereignis enthält unter `cached` den letzten außerhalb
der Hooks erfassten Status mit dessen Unix-Zeit `cached.at`; vor der
ersten Abfrage fehlt dieser Wert. Der Ereigniszeitpunkt `at` stammt
weiterhin aus `os.clock()`. Die beiden Zeitbasen dürfen nicht voneinander
abgezogen werden. Der ältere Status beschreibt keinen exakten Zustand
innerhalb des beobachteten nativen Aufrufs.

Die Statusdatei trennt `command_id` und `command_error` des zuletzt
bearbeiteten Terminalbefehls von `policy_id` der aktiven Slotfreigabe.
`load_request_id` bezeichnet den nativen Ladeversuch, zu dem
`load_phase` und `load_error` gehören. Während Dateilesung, Menüabschluss
oder Szenenwechsel weist die Probe neue Slot- und Ladebefehle mit
`load_in_progress` ab. Die aktive Freigabe bleibt dabei bestehen.
Nach Abschluss einen neuen Befehl senden, wenn ein weiterer Versuch
nötig ist.

Mit `--wait SEKUNDEN` wartet das Terminal auf einen frischen Status zur
eigenen Befehls-ID. Ohne `--load` bestätigt es die aktive Slotfreigabe.
Mit `--load` wartet es auf `scene_loaded` für dieselbe native Lade-ID.
Eine Ablehnung, ein bestätigter Ladefehler oder ein Ablauf der Wartefrist
liefert einen Fehlercode. Bei Fristablauf kann RE2 den Ladevorgang weiter
ausführen. Für `--wait` muss die installierte Probe die Befehls- und
Lade-ID melden. Ohne `--wait` gibt das Terminal nach dem Schreiben des
Befehls die ID zur manuellen Prüfung aus.

## Ablauf und Grenzen

Der Guard validiert vor dem Registrieren alle 26 verwendeten Methoden,
einschließlich Rückgabetyp und statischer Bindung. 20 davon betreffen
Speichern oder Löschen: Manager-Anforderungen, Manager-Speicherarbeiter
und die abgefangenen SaveService-Fassaden. Diese Aufrufe überspringen
den Originalrumpf und erhalten einen Null-/False-Rückgabewert. Die
Zuordnung zwischen Pre- und Post-Hook verwendet den Speicher der
jeweiligen verschachtelten Hook-Ausführung.

Szenarioladen ist auf den ausdrücklich freigegebenen Modus, Slot,
Szenariotyp und Zeitwert begrenzt. Latest-/Last-used- und mehrdeutige
Ladeabkürzungen bleiben gesperrt. Der bestätigte System-/Profilindex
`-1` darf gelesen werden; native 32-Bit-Argumente werden vor dem
Vergleich als vorzeichenbehaftet interpretiert. Diese Hooks sind keine
Garantie, dass jeder denkbare Engine- oder Plattformschreibpfad erfasst
ist. Beim tatsächlichen Laden wurde die statische
`SaveService.loadSingle`-Fassade nicht beobachtet.

Der Loader startet nur im nativen Titelflow, mit einem erkannten
Titel-/Haupt-/Kampagnenmenü, geschlossenem nativem Spielstanddialog
und bei freiem Save-Manager.
Nach `requestLoadGameData` bleibt er in `reading_save`, bis die native
Dateilesung beendet ist, der passende Ladepuffer existiert und
`isNoErrorLoad` den erfolgreichen Lesezustand bestätigt. Erst dann
schließt er in `closing_menu` die tatsächlich geöffneten Menüs über
deren eigene GUIMaster-Methoden: `closeTitleMenu`, `closeMenuMain`
beziehungsweise `closeMenuStory`. Diese nativen Abschlüsse betreuen
auch die zugehörigen Hilfsanzeigen und Effekte. Erst nach geschlossenen
Menüstatuswerten setzt der Loader den bestätigten `TitleFlow.State.FINALIZE`
über `set_StateValue`; der native Hauptflow führt den Szenenwechsel aus.
Die Schnittstellen einschließlich Parametertypen und Enumwert werden
vor einer Ladeanforderung geprüft. Ein ausgetauschter Titelflow beendet
die Probe. Der Loader ruft keine Speicherfunktion und keinen internen
Lade-Arbeiter direkt auf, leert keinen allgemeinen GUI-Container und
ruft `goLoadGameData` nicht mehr selbst auf.

`scene_loaded` verlangt einen frischen Observer-Nachweis nach der
Anforderung, passenden Slot und Szenariotyp, abgeschlossenen
Szenenladevorgang, verlassenen Titel-/Ladeflow und geschlossene
Titel-, Haupt-, Kampagnen- und Spielstandmenüs. Der temporäre
Ladepuffer ist dafür kein Abschlussnachweis. Ein verlorener Status
führt weder zu einer zweiten Ladeanforderung noch zu einem Neustart.

Der frühere direkte Szenenwechsel ließ das Titel-Overlay sichtbar.
Der gezielte native Menüabschluss ist jetzt am ersten Titelbild in einer
Instanz mit bereinigter Spieloberfläche bestätigt. Das ist weiterhin
eine lokale Entwicklerprobe; Host-/Gast-Ladebarriere und gemeinsames
Speichern fehlen. Andere Menüeinstiege sind nicht abgenommen.

**Offener Absturzpfad:** Nach einer vom Guard abgefangenen
Fortsetzen-Anforderung erschien die originale Fehlermeldung. Eine
anschließende konkrete alte-Slot-Anforderung endete in der Dateilesephase
mit einem Zugriffsausnahme-Absturz in `re2.exe` (`0xc0000005`).
Der neue Menüabschluss war noch nicht aufgerufen worden. Die Ursache
ist unbewiesen. Die Probe verweigert deshalb vorläufig jede weitere
kontrollierte Ladeanforderung in einer Sitzung mit abgefangenen
Ladeaufrufen (`native_load_state_requires_reset`). Sie stößt keine
automatischen Wiederholungen oder Prozessneustarts an. Das ist eine
Begrenzung der ungeprüften Fehlerbehandlung, kein Beweis einer
Absturzbehebung. Die Kampagnenmenü-Wiederholungsprüfung bleibt offen.
Für einen weiteren manuellen Test muss RE2 beendet und als frische
isolierte Spielinstanz gestartet werden. Ein Lua-/Skript-Reset ist keine
geprüfte Wiederherstellung des nativen Fehlerzustands; der derzeitige
Guard-Zähler allein weist keinen frischen Betriebssystemprozess nach.

## Nativer Nachweis am 15. November 2026

RE2 Steam-Build 11636119, REFramework d1461375, TDB 70, ursprüngliche
D3D12-Konfiguration, eine echte Spielinstanz:

- Das Originalmenü lud ausschließlich den freigegebenen alten Slot.
  Der Trace zeigte zunächst die asynchrone Dateilesung und danach
  `goLoadGameData`, `loadGameSaveData`, `delayLoadGameSaveData` und
  `setupLoadGameData`. Ein voreiliger Szenenwechsel im Anforderungsframe
  erreichte zuvor keine fertige Szene. Die korrigierte Reihenfolge
  erreichte passenden Slot, Szenariotyp und Spielerobjekt.
- `get_IsExistLoadedGameData` war nach abgeschlossenem Laden wieder
  falsch. `get_IsTitleSceneEnvironmentLoaded` blieb in der Kampagne
  wahr. Diese Werte allein beweisen keinen Titel- oder Ladeabschluss.
- Die erste Bildschirmaufnahme zeigte den verbliebenen Titel-Overlay-
  Fehler. Ein reiner FINALIZE-Übergang beseitigte diesen am Titelbild;
  beim Einstieg über das Kampagnenmenü blieb jedoch dessen Hilfszeile
  sichtbar, obwohl die einfachen Menüstatuswerte bereits falsch waren.
  Der zusätzliche native Menüabschluss berücksichtigt deshalb die
  Eigentümer dieser Hilfsanzeigen. Die aktuelle Fassung wurde vom
  ersten Titelbild geladen: Menüabschluss, anschließender nativer
  Szenenwechsel und bereinigte Spieloberfläche wurden erfasst.
- In einem vorherigen FINALIZE-Test funktionierten Bewegung (rund
  0,073 m bei S für 200 ms) und Öffnen/Schließen des Pausenmenüs.
  Diese Messung ist vom Nachweis der endgültigen Menüabschlussfassung
  getrennt. Deren Kampagnenmenü-Test wurde durch den oben beschriebenen
  Absturz während des Dateilesens beendet und gilt nicht als bestanden.
- Nach gesonderter ausdrücklicher Freigabe wurde genau einmal
  `requestSaveGameData` für den gesicherten alten Slot aufgerufen.
  Der installierte Hook zählte genau einen abgefangenen Aufruf, die
  API gab `false` zurück und der Save-Manager blieb inaktiv. Alle zwölf
  erfassten Speicherdateien behielten ihre SHA-256-Werte; keine neue
  Datei erschien. Das belegt diesen Einstiegspunkt in diesem Lauf,
  nicht alle 20 Schreib-/Löschmethoden in der Engine.
- Die einmalige Prüfung lief über die native Terminal-Anbindung im
  Hintergrund. Es wurden keine Eingaben an eine andere aktive
  Anwendung gesendet. RE2 wurde danach beendet; Originalordner,
  Konfiguration und Diagnosedateien wurden wiederhergestellt. Der
  abschließende Vergleich bestätigte erneut zwölf unveränderte Dateien.
- Ein weiterer frischer Hintergrundlauf mit der integrierten Titelspur
  und der oben beschriebenen JSON-Spur erreichte vom Titelbild erneut
  `scene_loaded`: genau eine erlaubte Slot-Anforderung, keine
  abgefangene Ladeanforderung, kein erfasster Speicheraufruf, passender
  Slot und frisches Spielerobjekt. Das native Log bestätigt die
  Hook-Installation sowie `closeTitleMenu`, danach FINALIZE und
  `goLoadGameData`, anschließend `unloadTitleEnvironment` und den
  abgeschlossenen Ladeflow. Sieben der 17 Titel-Hookziele wurden dabei
  tatsächlich aufgerufen. Dieser Lauf verwendete keine Tastatur- oder
  Mauseingabe und keine aktive Bildschirmaufnahme. Er bestätigt weder
  den sichtbaren Menüabschluss erneut noch den Kampagnenmenü- oder
  Fehlerpfad. Nach dem beabsichtigten Prozessende wurden die
  Originaldateien zurückgestellt und zwölf unveränderte Speicherdateien
  ohne neue Datei bestätigt. Der frühere Absturz gilt weiter als offen.
- Die getrennten Befehls-, Policy- und Lade-IDs wurden anschließend in
  einer frischen Titelbild-Instanz geprüft. Ein ursprünglicher
  `--load --wait`-Befehl erreichte seinen eigenen `scene_loaded`-Abschluss.
  Während `closing_menu` wurde ein zweiter Arm-Befehl mit demselben
  vorab datumsgeprüften alten Slotverweis direkt ins lokale Postfach
  gestellt. Dessen Ergebnisabfrage meldete `load_in_progress`; die aktive
  Policy und die native Lade-ID des ersten Befehls blieben erhalten.
  Es gab genau einen nativen Leseaufruf und keinen erfassten Speicheraufruf.
  Eine neue Arm-Anforderung nach abgeschlossenem Laden wurde per `--wait`
  bestätigt, ohne die vorherige Lade-ID oder deren Ergebnis zu ersetzen.
  Originaldateien wurden nach Prozessende zurückgestellt; zwölf Dateien
  blieben bytegleich, keine neue erschien. Andere Überlappungsphasen
  sowie der Kampagnenmenü- und Fehlerpfad sind damit nicht abgenommen.

Nach jedem Test wurden RE2 beziehungsweise das bestätigte Prozessende,
Originalordner, Konfiguration und Diagnosedateien geprüft. Auch nach
dem Absturz blieben alle zwölf erfassten Speicherdateien unverändert;
keine neue Datei erschien. Private Aufnahmen und Fehlerberichte werden
nicht veröffentlicht.

Lua-Tests prüfen simuliert unter anderem Schreibabweisung, verschachtelte
Hook-Aufrufe, geänderte Metadaten, vorzeichenbehaftete Argumente,
asynchrones Lesen, Titelbindung, gezielte Menüabschlüsse, unverändert
gehaltene In-Flight-Anforderungen, Schließfehler, abgefangene native
Ladevorgänge, echte statt vorgetäuschter Diagnosezustände und frische
Spielerbeobachtungen. Python-Tests prüfen CLI, Datumsfilter, Identität und
Fristen. Ein zweiter PC mit eigenem Steam-Konto ist derzeit nicht
verfügbar. Die Zwei-Instanzen-Abnahme sowie sämtliche Gameplay-, Welt-,
Cutscene- und Speicheranforderungen aus STATUS.md bleiben erforderlich.

## Titel- und Ladeablauf protokollieren

Für einen isolierten Diagnose-Lauf `reframework/diagnostics/re2_coop_title_trace.lua`
zusätzlich in den Autorun-Ordner kopieren. Die integrierte Fassung fragt
17 Hook-Registrierungen an: Titel-Setup und Zustandsetter, Ladeflow,
Titel-/Haupt-/Kampagnenmenü und die drei vom Ladeadapter verwendeten
GUIMaster-Abschlüsse. Fehlende Methoden werden einzeln als `unavailable`
gemeldet. Eine erfolgreiche Registrierungsanforderung ersetzt nicht die
Bestätigung der Hook-Installation im nativen REFramework-Log.

`RE2_COOP_TITLE_TRACE` protokolliert höchstens 128 Ein-/Austrittsereignisse
mit `enter` und `leave`. Die Hooks rufen das Original auf und geben dessen
Rückgabewert unverändert weiter, auch bei einem Fehler im Logger.
`requested_state` bezeichnet das Argument des beobachteten Zustandsetters.
`cached=[...]` ist ausdrücklich der zuletzt außerhalb der Hooks gelesene
Status, kein exakter Zustand während dieses Aufrufs. Die nächste
UpdateBehavior-Abfrage nach einem Ereignis sowie regelmäßige Abfragen
erfassen Titelzustand, Ladeflow, Save-Manager-Status, Ladepuffer und die
vier Menüstatuswerte. Innerhalb der nativen Hooks werden keine
Spiel-Getter aufgerufen. Die Ablaufspur ruft selbst keine Menü-, Lade-
oder Speicherfunktion auf.

Die ursprüngliche Fassung aus [PR #49](https://github.com/Maaviis/re2-remake-coop/pull/49)
protokollierte laut ihrem nativen Test zwölf Hook-Registrierungen auf
RE2 Build 11636119, REFramework d1461375 und TDB 70.
Der Start ohne Menüeingabe protokollierte
`TitleFlow.setup` sowie die numerischen Titelzustände 0, 4 und 100. Ein Wiederholungslauf
erfasste zusätzlich den kurzen Zwischenzustand 6.
Der Ladeflow blieb aus. In diesem Startlauf wurde kein Aufruf von
`TitleRBehavior.open` beobachtet. Die Zahlen dokumentieren beobachtete
Engine-Werte ohne Zuordnung zu sichtbaren UI-Zuständen.

Für die Ursachenprüfung zwei frische Logläufe desselben freigegebenen
Testslots vergleichen. Ein Lauf nutzt die ursprüngliche Menübedienung,
der andere die kontrollierte Ladeprobe. Die Reihenfolge der Menüaufrufe
mit `goLoadGameData`, `unloadTitleEnvironment` und dem sichtbaren
Overlay abgleichen. Der Startlauf bestätigt die Funktion der Ablaufspur.
Der direkte Titelbild-Einstieg des Ladeadapters ist inzwischen wie oben
beschrieben bestätigt. Die erweiterte Ablaufspur mit 17 Zielen ist durch
Lua-Tests und den ergänzenden nativen Titelbild-Lauf geprüft. Darin wurden
sieben Hookziele tatsächlich aufgerufen; die übrigen Aufrufpfade sind
weiter offen. Die Spur soll beim nächsten isolierten Vordergrundlauf
insbesondere den Abschluss aus dem Kampagnenmenü begleiten. Nur diese ergänzende
Titel-Ablaufspur verwenden; weitere ad-hoc-Titelspuren desselben Laufs
nicht parallel installieren.

Herkunft der Beiträge, kombinierte Prüfungen und Reihenfolge der nächsten
nativen Tests stehen in [INTEGRATION_LOAD_TOOLS.md](INTEGRATION_LOAD_TOOLS.md).
