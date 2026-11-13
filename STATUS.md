# Anforderungsaudit für RE2 Remake Koop

Stand: 12. November 2026. Eine erfüllte Anforderung benötigt einen Test mit zwei echten Spielinstanzen. Die Tests des lokalen Python-Protokolls gelten dafür ausdrücklich nicht als Nachweis.

| Anforderung | Befund | Nachweis, der noch fehlt |
|---|---|---|
| Zwei Spieler in einer Kampagne | Eine veröffentlichte Fremdmod bewirbt eine Zwei-Spieler-Beta; unser Prototyp läuft nicht im Spiel. | Beide Spieler starten denselben Kampagnenabschnitt und können unabhängig handeln. |
| Position und Aktionen | Loopback-Tests übertragen Position und Rotation zum v1-Gast und prüfen die Ausblendung bei Abwesenheit oder abgelaufener Quelle. Simulierte REFramework-Callbacks prüfen Marker, Transform und Ressourcenbindung am eigenen Testobjekt. Mesh und Material der statischen Schaufensterpuppe sind im Spielarchiv von Build 11636119 vorhanden. | Beobachter, Marker, Transform und sichtbare Schaufensterpuppe in RE2 TDB 70 prüfen. Danach eine animierte Spielfigur anbinden und Bewegung, Schießen, Interaktion und Animation mit zwei Spielinstanzen testen. |
| Gegner, Schaden und Tod | Im Modell repräsentiert; ein Synchronisationsnachweis im Spiel fehlt. | Gemeinsame Gegner-IDs, Gesundheit, Treffer, Tod und KI in beiden Instanzen. |
| Rätsel und Türen | Im Modell repräsentiert; Engine-Anbindung fehlt. | Jede Zustandsänderung wirkt in beiden Instanzen und bleibt nach Laden erhalten. |
| Gegenstände und Inventar | Im Modell repräsentiert; REFramework-Probe hat den Typ `app.ropeway.survivor.Inventory` im Spiel bestätigt. | Konkrete Inventarfelder und Aufnahme, Verbrauch, Transfer sowie Wiederverbindung in beiden Instanzen prüfen. |
| Fortschritt und Skriptereignisse | Im Modell repräsentiert; sämtliche Kampagnenpfade unkartiert. | Vergleich der Fortschrittsflags und Ereignisreihenfolge über die gesamte Kampagne. |
| Alle Zwischensequenzen | Nur ein abstrakter Cutscene-Zustand im Modell. | Beide Instanzen zeigen Beginn, Zeitverlauf, Skip und Ende synchron für jede Szene. |
| Keine Abweichung, Wiederverbindung | Der v1-Diagnosegast blendet bei erkanntem Verbindungsverlust die Pose aus und übernimmt beim Rejoin den verifizierten Snapshot derselben Sitzung. Loopback-Tests decken TCP-Reset, Sequenzlücken, falsche Digests, ungültige Snapshots und einen blockierten Host mit offenem Socket ab. | Abbruch während Kampf, Rätsel und Szene in RE2 prüfen. Beide Spielinstanzen müssen nach Rejoin dem Host-Zustand entsprechen. |
| Steam-Einladung | Fremdmod-Anleitung nennt Raumcode über Steam; direkte Freunde-Einladung ist nicht verifiziert. Unser Prototyp nutzt lokales TCP. | Zwei Steam-Konten: Einladung, Annahme, Lobby-Beitritt und Fehlerfälle. |
| Lobby im Stil des Originalmenüs | Fremdmod nennt „Main Menu > Multiplayer“; visuelle und funktionale Anforderungen nicht getestet. | Im Spiel prüfbare Auswahl von Speicherstand, Einstellungen, Status und Bereitschaft. |
| Gemeinsames Speichern und Laden | Eigenes JSON-Checkpointformat ist kein RE2-Speicherstand. | Host und Gast setzen denselben echten RE2-Spielstand fort. |

## Vorhandene Fremdmod

Die [Nexus-Dateiseite](https://www.nexusmods.com/residentevil22019/mods/3118?tab=files) und [Beschreibung](https://www.nexusmods.com/residentevil22019/mods/3118?tab=description) einer bestehenden Multiplayer-Mod nennen ein RT-Paket, Menü, Raumcode, Steam/LAN/IP und bekannte Probleme. Das sind Produktangaben, keine erfolgreiche Prüfung der geforderten vollständigen Synchronisation.

Die [Nexus-Berechtigungen](https://www.nexusmods.com/residentevil22019/mods/3118?tab=description) verlangen für Änderungen an den Dateien des Autors dessen Erlaubnis. Deshalb bleibt unsere Implementierung eigenständig. Die vorhandene Mod kann als Vergleich in einem gesonderten Testlauf dienen; ihre Skripte werden weder übernommen noch verändert.

## Testprotokoll für echte Spielinstanzen

Für jeden Test: RE2-Build, REFramework-Build, Mod-Version, Steam-Konto, Host/Gast-Rolle, Spielstand, Szenenkennung und Zeitstempel erfassen. Jede Instanz protokolliert lokal dieselben stabilen Objekt-IDs und Zustandswerte. Ein Test gilt nur dann als bestanden, wenn beide Wertefolgen nach definierter Latenztoleranz übereinstimmen und nach Wiederverbindung gleich bleiben. Für Cutscenes müssen Beginn, Fortschritt, Skip und Ende einzeln verglichen werden.

Ohne zwei gleichzeitig gestartete RE2-Instanzen, zwei Konten und lesbare Zustandsmessung bleibt der Spielnachweis offen.
