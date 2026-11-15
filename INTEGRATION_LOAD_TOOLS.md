# Gemeinsamer Prüfstand für Laden und Steam-Werkzeuge

Dieser Entwicklungszweig baut auf dem Ladeadapter aus
[PR #50](https://github.com/Maaviis/re2-remake-coop/pull/50) auf. Er übernimmt
nur die abgegrenzten Beiträge von bySenom, ohne die offenen PRs zu mergen:

| Herkunft | Übernommener Beitrag | Anpassung im gemeinsamen Stand |
|---|---|---|
| [#48, e10e935](https://github.com/Maaviis/re2-remake-coop/commit/e10e935a72f4c5e647b9897a17a54715785256bf) | Lesender Steam-Preflight, fünf Tests und Anleitung | Neue Fehlerprüfung für nicht lesbare Dateimetadaten; sechs Preflight-Tests |
| [#49, e1b3cca](https://github.com/Maaviis/re2-remake-coop/commit/e1b3ccafe3c440ca5631c93245ed44e2cf497f21) | Passive Titel-/Lade-Ablaufspur und Anleitung | Zusätzliche bestätigte Menüeinstiege, Ein-/Austrittsprotokoll und Lade-/Menüstatus außerhalb der Hooks |
| #50, 619b6c0 | Kontrollierter Ladeadapter, gezielter Menüabschluss und Fehlergrenzen | Unverändert übernommen; keine neue Lade- oder Speicherfunktion durch diese Integration |

Die drei ursprünglich hinzugefügten Quelldateien wurden vor den
Anpassungen über ihre Git-Blob-Hashes mit den Einzelcommits verglichen.
Der ältere Gesamtzweig von #48 wurde nicht übernommen. Die neueren
Lade-, Lobby-, Sitzungs- und Fehlerprüfungen bleiben erhalten.

## Was der gemeinsame Test belegt

Die vollständige Python-Prüfung umfasst Protokoll, Bridge, Lobby,
Katalog, Lade-CLI und Preflight. Der Preflight verwendet dabei dieselben
Observer- und Posenfunktionen wie die aktuelle Steam-Bridge. Seine
positiven Tests simulieren Prozess und Pipe; ein `ready=true` aus diesen
Tests ist kein nativer Zwei-Rechner-Nachweis.

Die Lua-Suiten prüfen zusätzlich den durchleitenden Titel-Tracer:
unveränderte Rückgabewerte, unveränderte Originalaufrufe, keine
Spiel-Getter innerhalb der nativen Hook-Callbacks, begrenzte Protokolle,
fehlende Typen, fehlende Statusquellen und Loggerfehler. Die Quelle des
gespeicherten Status ist mit `cached` gekennzeichnet. Die erweiterte Spur
hat inzwischen einen ergänzenden nativen Titelbild-Lauf: 17
Registrierungen und die Installation wurden protokolliert, sieben
Hookziele tatsächlich aufgerufen. Die sichtbare Kampagnenmenü-Prüfung
und der offene Fehlerpfad sind damit nicht abgenommen.

Auch die ältere JSON-Ablaufspur der Ladeprobe führt nun keine
diagnostischen Spielabfragen in ihren sieben nativen Hooks aus.
Ein-/Austritte enthalten den letzten unverändert aufbewahrten
Update-Status unter `cached`, einschließlich eigener Abfragezeit.
Erweiterte Lua-Prüfungen erkennen Getter-Wiedereintritt auch dann,
wenn eine geschützte Ausführung die ausgelöste Ausnahme auffangen
würde. Sie prüfen außerdem Rückgabewerte, fehlende Anfangsdaten,
unveränderte ältere Samples, die 64-Ereignisgrenze und Diagnosefehler.

Ein lesender CLI-Test bei geschlossenem RE2 muss Exitcode 1 und einen
Negativbericht liefern. Er darf keine Lobby erzeugen, keine Einladung
senden und keine Pipe ansprechen, solange der Prozess nicht zur
angegebenen Installation gehört. Dateiabweichungen der wiederhergestellten
Originalinstallation sind in diesem Fall erwartete Befunde; sie werden
nicht durch eine ungeprüfte Neuinstallation beseitigt.

Die automatisierten Integrationsprüfungen starten RE2 nicht. Ein
separater frischer nativer Hintergrundlauf lud ausschließlich den alten
freigegebenen Slot und erreichte erneut `scene_loaded`. Die Spur erfasste
nativen Menüabschluss, FINALIZE, Szenenwechsel und Ladeende. Ohne
Vordergrundbedienung oder Bildschirmaufnahme erweitert das nur den
Titelbild-/Ablaufnachweis. Nach dem beabsichtigten Prozessende wurden
Originaldateien zurückgestellt; alle zwölf Speicherdateien blieben
bytegleich, keine neue erschien. Einzelheiten und der weiter offene
Absturzpfad stehen in [READONLY_LOAD.md](READONLY_LOAD.md).
Kampagnenmenü, Fehlerbehandlung, gemeinsame Ladebarriere, Speichern und
sämtliche Zwei-Instanzen-Anforderungen aus STATUS.md bleiben offen.

## Nächster nativer Lauf

1. Pro Spielinstallation einen Testführer sowie dessen tatsächlich
   gestartete Prozess-ID und Startzeit protokollieren. Bestehende fremde
   Instanzen nicht beenden. Sicherungen und isolierte Mod-Ordner werden
   von genau diesem Lauf verwaltet und anschließend zurückgestellt.
2. Frische RE2-Instanz mit dem festgelegten Build, passenden Dateien und
   vollständiger geprüfter Sicherung verwenden. Ein Lua-Reset beweist
   keinen frischen nativen Fehlerzustand. Nur die freigegebenen
   Spielstände vom 11.11.2026 sind für lokale Tests zulässig.
3. Den Preflight für den Steam-Posentest und die native Ladeprobe getrennt
   behandeln: Ein lokaler Menütest benötigt keinen bestätigten Gast;
   der positive Steam-Preflight verlangt Lobbyrolle, Roundtrip und Pose
   auf beiden echten Testrechnern. Dateien auf der Festplatte allein
   beweisen nicht den geladenen Laufzeitstand.
4. Vor der Ladeanforderung aktuelle Katalogreferenz, freien Save-Manager,
   erlaubten Menüstatus und `denied_loads=0` prüfen. Nach einer
   abgefangenen Ladeabkürzung keine weitere kontrollierte Anforderung
   in derselben Guard-Sitzung senden. Die native Fehlerbehandlung bleibt
   ungeprüft; keine automatische Wiederholung und kein Neustart allein
   wegen einer abgelaufenen Beobachtungsfrist.
5. Spielaktionen ausschließlich über Terminalhelfer ausführen, die
   Vordergrundprozess und tatsächliche Fenstergrenzen prüfen. Nach
   jedem Menüschritt Eingaben vollständig loslassen und den neuen
   Bildschirm sowie Status prüfen. Keine Serienbestätigungen über
   Menügrenzen hinweg: Im vorigen Lauf erreichte eine Bestätigung
   unbeabsichtigt die Fortsetzen-Abkürzung.
6. Ein- und Austrittsereignisse der gezielten Menüabschlüsse mit
   `closing_menu`, FINALIZE, dem nativen Szenenwechsel und einer aktiven
   Bildschirmaufnahme vergleichen. Auch Hilfszeile, Eingabehinweise,
   Interaktionsanzeige und Pausenmenü prüfen. Ein falscher Busy-Wert
   allein beweist nicht, dass alle Menüelemente verschwunden sind.
7. Bei verzögerten Statusmeldungen zuerst den eigenen gestarteten Prozess
   erneut prüfen. Einen lebenden Ladeversuch nicht als beendet behandeln.
   Nach tatsächlichem Prozessende Ergebnisse sichern, Originaldateien
   zurückstellen und alle erfassten Speicherdateien vergleichen. Persönliche
   Aufnahmen, Logs, Speicherstände und Kontodaten bleiben lokal.
