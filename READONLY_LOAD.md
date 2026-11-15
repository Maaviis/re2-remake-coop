# Kontrollierte native Ladeprobe

Dieser Entwurf ergänzt den Katalog aus #45 und die Eingabe aus #46 um
eine ausdrücklich aktivierte Entwicklerprobe. Er ist kein gemeinsamer
Kampagnenstart. Die normalen Lobby-Skripte laden oder speichern dadurch
weiterhin keinen Spielstand.

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
Policy-ID, abgefangene Aufrufe, Ladephase und Fehler. Die Zahl `hooks`
zählt konfigurierte Hooks; sie ersetzt keine Bestätigung der Installation
im REFramework-Log. `allowed_load_calls` zählt erlaubte Aufrufe, keine
erfolgreich abgeschlossenen Ladevorgänge.

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

Der Loader startet nur im nativen Titelflow und bei freiem Save-Manager.
Nach `requestLoadGameData` bleibt er in `reading_save`, bis die native
Dateilesung beendet ist, der passende Ladepuffer existiert und
`isNoErrorLoad` den erfolgreichen Lesezustand bestätigt. Erst dann
ruft er `goLoadGameData` auf. Er ruft keine Speicherfunktion, keine
Setter und keinen internen Lade-Arbeiter direkt auf.

`scene_loaded` verlangt einen frischen Observer-Nachweis nach der
Anforderung, passenden Slot und Szenariotyp, abgeschlossenen
Szenenladevorgang sowie verlassenen Titel-/Ladeflow. Der temporäre
Ladepuffer ist dafür kein Abschlussnachweis. Ein verlorener Status
führt weder zu einer zweiten Ladeanforderung noch zu einem Neustart.

**Offener Fehler:** Beim direkten Laden vom ersten Titelbild wurde die
Spielwelt steuerbar, das ursprüngliche Titel-Overlay blieb jedoch
sichtbar. `scene_loaded` bestätigt deshalb ausschließlich Szene und
Spielerobjekt. Menüabschluss, nutzbarer Kampagnenstart, Host-/Gast-
Ladebarriere und gemeinsames Speichern sind nicht abgenommen. Das
Overlay muss über den richtigen nativen Menülebenszyklus beendet werden.

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
- Die Bildschirmaufnahme zeigte den verbliebenen Titel-Overlay-Fehler.
  Eine kurze Rückwärtsbewegung veränderte die gemessene Spielerposition;
  das ersetzt keine Abnahme des Menüabschlusses.
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

Lua-Tests prüfen simuliert unter anderem Schreibabweisung, verschachtelte
Hook-Aufrufe, geänderte Metadaten, vorzeichenbehaftete Argumente,
asynchrones Lesen, Titelbindung, Fehlerzustände und frische
Spielerbeobachtungen. Python-Tests prüfen CLI, Datumsfilter, Identität und
Fristen. Ein zweiter PC mit eigenem Steam-Konto ist derzeit nicht
verfügbar. Die Zwei-Instanzen-Abnahme sowie sämtliche Gameplay-, Welt-,
Cutscene- und Speicheranforderungen aus STATUS.md bleiben erforderlich.

## Titel- und Ladeablauf protokollieren

Für einen isolierten Diagnose-Lauf `reframework/diagnostics/re2_coop_title_trace.lua`
zusätzlich in den Autorun-Ordner kopieren. Es registriert durchleitende Hooks
für `TitleFlow.setup`, den Start und das Ende des Ladeflows sowie
`open`, `close` und `doOnDestroy` der nativen Titel- und Hauptmenütypen.
Der REFramework-Logfilter `RE2_COOP_TITLE_TRACE` zeigt diese Aufrufe
und Änderungen der beobachteten Flow-Werte. Die Ablaufspur ruft selbst keine
Menü-, Lade- oder Speicherfunktion auf.

Auf RE2 Steam-Build 11636119 mit REFramework d1461375 und TDB 70 wurden
zwölf Hooks registriert. Der Start ohne Menüeingabe protokollierte
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
Die Ursache des Overlay-Problems und ein Abschalten über den
nativen Menülebenszyklus sind offen.
