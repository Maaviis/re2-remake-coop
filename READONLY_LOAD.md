# Kontrollierte native Ladeprobe

Dieser Entwurf erg�nzt den Katalog aus #45 und die Eingabe aus #46 um
eine ausdr�cklich aktivierte Entwicklerprobe. Er ist kein gemeinsamer
Kampagnenstart. Die normalen Lobby-Skripte laden oder speichern dadurch
weiterhin keinen Spielstand.

## Installation und Bedienung der Probe

Die Module `reframework/autorun/re2_coop/save_guard.lua` und
`readonly_loader.lua` werden erst durch `require` aktiv. Nur f�r einen
isolierten Test wird zus�tzlich
`reframework/diagnostics/re2_coop_readonly_save_probe.lua` ins
Autorun-Verzeichnis kopiert. **Diese Diagnose deaktiviert die von ihr
abgefangenen Speicher- und L�schaufrufe.** Sie geh�rt nicht in eine
Installation, mit der normaler Spielfortschritt gespeichert werden soll.
Vor einem Test vollst�ndige Sicherungen verwenden; danach die
Testinstallation entfernen und die Originaldateien zur�ckstellen.

Der native Katalogexporter und Observer m�ssen ebenfalls laufen.
Aus dem Projektverzeichnis kann eine datumsgefilterte Referenz freigegeben
werden, ohne einen Ladevorgang anzufordern:

```powershell
python readonly_save_control.py --data "<RE2>/reframework/data" --allow-save-date 2026-11-11 scenario:4
```

Nur mit dem zus�tzlichen Argument `--load` wird das native Lesen dieses
Slots angefordert. Das ist eine lokale Entwickleranweisung, keine
Netzwerknachricht und kein Startknopf der Lobby. Die CLI verlangt einen
frischen Guard-Status mit vollst�ndiger Hook-Konfiguration und einen
frischen, zum Datum passenden Katalogeintrag. Der native Guard pr�ft
Slot, Szenario und Zeitwert erneut an der vorhandenen Engine-Tabelle.
Der Metadatenverweis best�tigt nicht den Inhalt der Speicherdatei.

Die lokale Datei `re2_coop_save_guard.json` meldet die angenommene
Policy-ID, abgefangene Aufrufe, Ladephase und Fehler. Die Zahl `hooks`
z�hlt konfigurierte Hooks; sie ersetzt keine Best�tigung der Installation
im REFramework-Log. `allowed_load_calls` z�hlt erlaubte Aufrufe, keine
erfolgreich abgeschlossenen Ladevorg�nge.

## Ablauf und Grenzen

Der Guard validiert vor dem Registrieren alle 26 verwendeten Methoden,
einschlie�lich R�ckgabetyp und statischer Bindung. 20 davon betreffen
Speichern oder L�schen: Manager-Anforderungen, Manager-Speicherarbeiter
und die abgefangenen SaveService-Fassaden. Diese Aufrufe �berspringen
den Originalrumpf und erhalten einen Null-/False-R�ckgabewert. Die
Zuordnung zwischen Pre- und Post-Hook verwendet den Speicher der
jeweiligen verschachtelten Hook-Ausf�hrung.

Szenarioladen ist auf den ausdr�cklich freigegebenen Modus, Slot,
Szenariotyp und Zeitwert begrenzt. Latest-/Last-used- und mehrdeutige
Ladeabk�rzungen bleiben gesperrt. Der best�tigte System-/Profilindex
`-1` darf gelesen werden; native 32-Bit-Argumente werden vor dem
Vergleich als vorzeichenbehaftet interpretiert. Diese Hooks sind keine
Garantie, dass jeder denkbare Engine- oder Plattformschreibpfad erfasst
ist. Beim tats�chlichen Laden wurde die statische
`SaveService.loadSingle`-Fassade nicht beobachtet.

Der Loader startet nur im nativen Titelflow und bei freiem Save-Manager.
Nach `requestLoadGameData` bleibt er in `reading_save`, bis die native
Dateilesung beendet ist, der passende Ladepuffer existiert und
`isNoErrorLoad` den erfolgreichen Lesezustand best�tigt. Erst dann
ruft er `goLoadGameData` auf. Er ruft keine Speicherfunktion, keine
Setter und keinen internen Lade-Arbeiter direkt auf.

`scene_loaded` verlangt einen frischen Observer-Nachweis nach der
Anforderung, passenden Slot und Szenariotyp, abgeschlossenen
Szenenladevorgang sowie verlassenen Titel-/Ladeflow. Der tempor�re
Ladepuffer ist daf�r kein Abschlussnachweis. Ein verlorener Status
f�hrt weder zu einer zweiten Ladeanforderung noch zu einem Neustart.

**Offener Fehler:** Beim direkten Laden vom ersten Titelbild wurde die
Spielwelt steuerbar, das urspr�ngliche Titel-Overlay blieb jedoch
sichtbar. `scene_loaded` best�tigt deshalb ausschlie�lich Szene und
Spielerobjekt. Men�abschluss, nutzbarer Kampagnenstart, Host-/Gast-
Ladebarriere und gemeinsames Speichern sind nicht abgenommen. Das
Overlay muss �ber den richtigen nativen Men�lebenszyklus beendet werden.

## Nativer Nachweis am 15. November 2026

RE2 Steam-Build 11636119, REFramework d1461375, TDB 70, urspr�ngliche
D3D12-Konfiguration, eine echte Spielinstanz:

- Das Originalmen� lud ausschlie�lich den freigegebenen alten Slot.
  Der Trace zeigte zun�chst die asynchrone Dateilesung und danach
  `goLoadGameData`, `loadGameSaveData`, `delayLoadGameSaveData` und
  `setupLoadGameData`. Ein voreiliger Szenenwechsel im Anforderungsframe
  erreichte zuvor keine fertige Szene. Die korrigierte Reihenfolge
  erreichte passenden Slot, Szenariotyp und Spielerobjekt.
- `get_IsExistLoadedGameData` war nach abgeschlossenem Laden wieder
  falsch. `get_IsTitleSceneEnvironmentLoaded` blieb in der Kampagne
  wahr. Diese Werte allein beweisen keinen Titel- oder Ladeabschluss.
- Die Bildschirmaufnahme zeigte den verbliebenen Titel-Overlay-Fehler.
  Eine kurze R�ckw�rtsbewegung ver�nderte die gemessene Spielerposition;
  das ersetzt keine Abnahme des Men�abschlusses.
- Nach gesonderter ausdr�cklicher Freigabe wurde genau einmal
  `requestSaveGameData` f�r den gesicherten alten Slot aufgerufen.
  Der installierte Hook z�hlte genau einen abgefangenen Aufruf, die
  API gab `false` zur�ck und der Save-Manager blieb inaktiv. Alle zw�lf
  erfassten Speicherdateien behielten ihre SHA-256-Werte; keine neue
  Datei erschien. Das belegt diesen Einstiegspunkt in diesem Lauf,
  nicht alle 20 Schreib-/L�schmethoden in der Engine.
- Die einmalige Pr�fung lief �ber die native Terminal-Anbindung im
  Hintergrund. Es wurden keine Eingaben an eine andere aktive
  Anwendung gesendet. RE2 wurde danach beendet; Originalordner,
  Konfiguration und Diagnosedateien wurden wiederhergestellt. Der
  abschlie�ende Vergleich best�tigte erneut zw�lf unver�nderte Dateien.

Lua-Tests pr�fen simuliert unter anderem Schreibabweisung, verschachtelte
Hook-Aufrufe, ge�nderte Metadaten, vorzeichenbehaftete Argumente,
asynchrones Lesen, Titelbindung, Fehlerzust�nde und frische
Spielerbeobachtungen. Python-Tests pr�fen CLI, Datumsfilter, Identit�t und
Fristen. Ein zweiter PC mit eigenem Steam-Konto ist derzeit nicht
verf�gbar. Die Zwei-Instanzen-Abnahme sowie s�mtliche Gameplay-, Welt-,
Cutscene- und Speicheranforderungen aus STATUS.md bleiben erforderlich.
