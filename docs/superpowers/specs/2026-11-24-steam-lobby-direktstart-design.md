# Koop direkt aus dem Steam-Spielstart

## Bedienung

Beide Spieler starten RE2 in ihrer Steam-Bibliothek. Einer erstellt im Multiplayer-Menü die private Lobby, der andere tritt bei. Der Host wählt „Neues Spiel“, Szenario und Schwierigkeit. Nach beiderseitiger Bereitschaft lädt jede Instanz die Welt im bereits laufenden RE2-Prozess. Dafür genügt ein Konto ohne Szenario-Spielstand. Auch ein erstmalig gestartetes, noch leeres Testprofil gehört zur Abnahme.

Der Host führt pro Koop-Kampagne den gemeinsamen Weltstand und ein eigenes Inventar für jeden Steam-Mitspieler. Beim ersten Beitritt erhält der Gast die reguläre Startausrüstung der gewählten Host-Figur. Spätere Fortschritte des Hosts verändern diese Grundausstattung nicht. Beim Wiederbeitritt lädt der Gast sein Inventar aus dem letzten gültigen Koop-Checkpoint beim Host.

## Entscheidung und vorhandene Bausteine

Der Nutzer hat den normalen Steam-Start gewählt. Ein separater Starter könnte vor Prozessbeginn eine Arbeitskopie bereitstellen, würde aber einen anderen Einstieg erfordern. Der bisherige Helfer in PR #155 verschiebt den aktiven Speicherordner und verlangt deshalb ein geschlossenes Spiel. Beim dokumentierten Versuch verlor dieser Helfer vor Prozessende seinen aktuellen Cloud-Nachweis. Eine längere Wartezeit erfüllt das gewünschte Bedienverhalten nicht.

Der neue Weg benutzt die vorhandene Lobby, die native Initialisierung in `new_game.lua`, die bestätigte Weltpause und den beiderseitigen Checkpoint-Abgleich. Der technisch offene Teil liegt zwischen der Wahl von Multiplayer im Titelmenü und der ersten Freigabe eines Engine-Aufrufs. Maavis Arbeit an nativem Speichern und Fortsetzen bleibt die Schnittstelle für Checkpoints. Seine Prüfsummen und Herkunftsnachweise werden nach Sichtung des tatsächlich verfügbaren Integrationsstands wiederverwendet.

## Schutz und Übergänge

Der erste Implementierungsschritt ist ein Nachweis auf einem entbehrlichen Profil, ob der laufende RE2-Build im ruhenden Titelmenü seine Speicherzugriffe dauerhaft auf einen separaten Koop-Bestand binden kann. Die bestehende Steam-Sperre und die native Dateisperre dienen als zusätzliche Belege. Eine bestätigte Umleitung für Engine-Schreibvorgänge einschließlich bereits geöffneter Handles und Autosaves steht aus. Der bestehende Verzeichniswechsel darf weiterhin nur bei geschlossenem Spiel laufen. Der Einzelspielerbetrieb muss normal funktionieren.

Beim Wählen von Multiplayer kann die Vorbereitung im Hintergrund beginnen. Die Lobby darf sich währenddessen öffnen. Freigabe zum Kampagnenstart erfordert auf beiden Seiten die bestätigte Isolation im aktuellen Prozess und die in #155 vorhandenen Prüfungen für Steam-Mitgliedschaft, Peer, Bereitschaft und Startversuch. Die Cloud-Abfrage bleibt für die erste Abnahme aktiv. Scheitert die Isolation, zeigt das Menü den konkreten fehlenden Nachweis. Es startet weder einen neuen Prozess noch die Engine auf einem ungeklärten Speicherziel. Bei Verbindungsverlust verfällt die alte Freigabe. Rückkehr zum Einzelspieler verlangt die bestätigte Wiederherstellung seines Speicherziels.

## Inventar und Fortsetzen

Im lokal installierten RE2-Programm enthält die TDB-70-Typdatenbank statische Getter und Setter für `via.storage.saveService.SaveService.SaveMountPath` und `SaveDirectoryPath`. Sie enthält auch `get_LastSaveResult()` und `get_LastSaveFailed()`. Das sind Kandidaten für den isolierten Versuch. Vor einem Aufruf die aktive Implementierung und ihre Zuständigkeit für RE2-Szenario-Slots prüfen. Eine erfolgreiche Pfad-Rücklesung allein reicht nicht. Ein durch Spielgeschehen ausgelöster Autosave muss im getrennten Bestand vollständig ankommen, von RE2 wieder geladen werden können und die privaten Testdateien bytegleich lassen. Das ist auch nach einem Prozessabbruch zu prüfen.

Eine dauerhafte Kampagnenkennung und die Steam-Identität des tatsächlich verbundenen Peers adressieren den Inventarstand. Anzeigename, Rolle und temporäre Lobby-Kennung eignen sich nicht als dauerhafter Schlüssel. Die Grundausstattung wird beim Beginn der Kampagne aus dem von RE2 erzeugten Anfangszustand gewonnen und beim Host festgehalten. Sie bleibt auch für einen später erstmals beitretenden Gast verfügbar. Es werden keine Slotdateien konstruiert.

Die Inventarleser erfassen unter anderem Slots, Mengen, Ausrüstung und Schnellzugriffe. Das native Anwenden und erneute Auslesen eines solchen Zustands beim Gast ist ein eigener Integrationsschritt. Bei der Übernahme eines Checkpoints prüft der Host Kampagne, Peer und Checkpoint-Generation. Erst eine vollständige Generation mit Weltstand und zugehörigen Spielerständen ersetzt die letzte gültige. Wiederholte Nachrichten, ein Abbruch oder ein anderer Gast dürfen keine fremden Inventare übernehmen oder Gegenstände verdoppeln. Eine beschädigte vorhandene Spielerdatei muss als Wiederherstellungsfehler sichtbar sein. Die Übertragung ist auf den benötigten Koop-Zustand begrenzt.

## Abnahme und aktueller Stand

Bei der Wiederaufnahme gilt die Reihenfolge Weltcheckpoint laden, beide Instanzen in ihrer bestätigten Pause halten, persönliches Inventar zuweisen, aus der Engine zurücklesen und erst dann gemeinsam freigeben. Differierende Munitionsmengen zwischen Host und Gast sind zulässig. Entscheidend ist die Übereinstimmung jedes Spielers mit seinem eigenen gespeicherten Zustand. Der Host übernimmt bei jeder neuen Generation auch die letzten bestätigten Inventare gerade abwesender Spieler.

1. E2 prüft Erstbeitritt, unterschiedliche Gastkonten, abgebrochenes Speichern, wiederholtes Zustellen und Wiederbeitritt in einer neu erstellten Lobby. Veraltete Prozess-, Kampagnen- und Peer-Bindungen müssen scheitern.
2. E3 verwendet ein isoliertes Windows-Testprofil mit geprüfter Rücksicherung. Normal über Steam starten, Prozess-ID vor der Menüwahl und nach dem Laden vergleichen, den nativen Weltübergang und einen echten Autosave-Auslöser beobachten. Speicherziele und Schreibresultate erfassen. Inventar, Hashes und Wiederherstellung der privaten Testdateien vor und nach dem Lauf vergleichen. Den Fall eines bereits offenen schreibbaren Handles und die Rückkehr zum Einzelspieler separat prüfen.
3. E4 verlangt zwei PCs und unterschiedliche Steam-Konten. Beide starten erstmals ohne Szenario-Slot. Der Gast verbraucht Munition, beide bestätigen einen echten Checkpoint und beenden die Sitzung. Beim Wiederbeitritt mit derselben Kampagne muss der Gast seine verbleibende Munition tatsächlich in RE2 sehen und nutzen können. Ein weiteres Konto erhält die normale Startausrüstung. Bei Alt+Tab und Wiederverbindung gelten weiterhin die vorhandenen Lobby-Anforderungen.

Der unveränderte Testbuild aus PR #155 erreicht E2 für den bereits geschützten Startversuch ohne Szenario-Slot. Für den hier beschriebenen Direktstart aus einem gewöhnlichen Steam-Prozess und die vollständige Wiederherstellung eines persönlichen Gastinventars ist die End-to-End-Funktion E0. Der technische Versuch endet bei einem fehlenden Nachweis mit einem Befund zum ersten blockierenden Zugriff.
