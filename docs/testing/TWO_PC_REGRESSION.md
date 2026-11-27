# Zwei-PC-Abnahme

## Jetzt prüfen · Phase A

Ziel ist eine belastbare Lobbyprüfung. Die erste neue Version ändert ausschließlich die Verarbeitung bereits abgelöster Gast-Begrüßungen beim Host. Der Nachweis für diesen Fehler ist ein Protokolltest. Es gibt bisher keinen Beleg dafür, dass eure beiden Abstürze dieselbe Ursache hatten.

1. Zwei PCs und zwei Steam-Konten mit isolierten RE2-Testprofilen verwenden. Auf beiden den ZIP-Hash mit `Get-FileHash -Algorithm SHA256 -LiteralPath <ZIP>` vergleichen, bei geschlossenem Spiel installieren und `re2-coop/build-info.json` prüfen. RE2 und REFramework auf beiden protokollieren. Private Save-Dateien und Steam-Cache vor und nach dem Test per SHA-256 vergleichen. Ohne isoliertes Profil und geprüfte Sicherung vor der Vorbereitung anhalten.
2. RE2 über Steam starten. Host öffnet eine private Lobby, Gast nimmt die Einladung an. Auf beiden die Rolle und „verbunden“ prüfen. Ein Klick ins Koop-Menü darf den darunterliegenden RE2-Menüpunkt nicht auslösen. Escape muss die Bedienung kontrolliert zurückgeben.
3. Für die normale Bereitschaft verlangt die aktuelle UI eine gültige Kampagnenwahl. Auf dem Host „Neues Spiel“, Leon A, Normal wählen. Nur bis zur Bereitschaft gehen. Wenn „Koop-Ordner vorbereiten“ hängt oder ein Prozess endet, Uhrzeit, Rolle und letzte Meldung festhalten und den Versuch beenden. Diese Überlappung mit der Vorbereitung ist Teil des Befunds.
4. Gast setzt „Bereit“, nimmt es zurück und setzt es erneut. Nach jedem Schritt beide Anzeigen vergleichen. Dann Host, Gast und schließlich beide nacheinander per Alt+Tab aus dem Spiel und zurück wechseln. Währenddessen Status auf dem anderen PC beobachten. Sitzung und Auswahl müssen erhalten bleiben. Eingabe und Cursor danach mit Maus, Tastatur und, falls verfügbar, Controller prüfen.
5. Gast verlässt die Lobby über das Menü. Auf dem Host muss die bisherige Gastbereitschaft erlöschen. Gast erneut einladen. Eine neue Begrüßung muss angenommen werden, beide Seiten müssen wieder denselben Zustand sehen. Gast setzt die Bereitschaft erneut. Ein neuer Stillstand, Crash oder ungewollter nativer Menüklick beendet den Lauf.
6. Für jeden Lauf Buildhash, Host- und Gaststartzeit samt Zeitzone, IDs von Sitzung und Beitritt, Revision vor/nach Rejoin und Ergebnisse der einzelnen Schritte festhalten. Die gemeinsame `reframework/data/re2_coop_logs/<Sitzung>/timeline.jsonl` vor dem nächsten Versuch sichern. Gastzeit und Empfangszeit beim Host getrennt lesen. Fehlende Gastdaten als Lücke markieren. Bei normalem Testerfolg nach Schritt 5 regulär beenden. Die Kampagne erst nach Freigabe von A testen.

## Matrix und spätere Abnahme

Alle E4-Felder für einen neuen Kandidaten beginnen offen. Pro Zeile Ergebnis, betroffene Rolle, ersten fehlerhaften Übergang und Beleg festhalten. „Nicht getestet“ und „fehlgeschlagen“ getrennt notieren. Eine gesperrte Phase bleibt offen. Beim standardmäßig deaktivierten synchronisierten Skip den Modus mit ins Protokoll aufnehmen.

| ID | Phase und Aktion | Beobachtbares Bestehenskriterium |
|---|---|---|
| R01 | A · Erstellen und beitreten | Richtige Rollen und gemeinsame Sitzung, beide verbunden. |
| R02 | A · Gast bereit, zurücknehmen, erneut bereit | Jede Änderung erscheint bei beiden einmal für die gültige Auswahl. |
| R03 | A · Fokus einzeln und beidseitig wechseln | Mitgliedschaft und Verbindung bestehen, Eingabe funktioniert nach Rückkehr. |
| R04 | A · Verlassen und wieder beitreten | Veraltete Bereitschaft erlischt, neuer Beitritt bleibt nach erneuter Bestätigung gültig. |
| R05 | B · Neues Spiel ohne Szenario-Slot | Gleiche Geschichte und Schwierigkeit auf beiden, Start im selben RE2-Prozess. |
| R06 | B · Ladebildschirm verlassen | Beide erreichen denselben Spielabschnitt und können unabhängig gehen und drehen. |
| R07 | C · Trucker-Intro und Autofahrt vollständig anschauen | Beide Instanzen zeigen Bild und Ton bis zum nativen Ende. |
| R08 | D · Host fordert Skip an | Einmalige Gastzustimmung gilt nur für dieses Vorkommen. |
| R09 | D · Gast fordert Skip an | Host kann ablehnen oder zustimmen, das Ergebnis stimmt auf beiden überein. |
| R10 | D · Beide fordern gleichzeitig an | Höchstens ein wirksamer Skip je Vorkommen. |
| R11 | C/D · Versetzte Ankunft, verspätete, doppelte, fehlende und fremde Nachrichten | Keine fremde oder abgelaufene Zustimmung, spätere gültige Ankunft kann fortfahren. |
| R12 | C/D · Gast trennt während der Szene | Klarer lokaler Zustand und sicherer Ausstieg, alte Stimmen verfallen beim Beitritt. |
| R13 | C/D · Trucker, Auto, Ladeneingang in Folge | Richtige Reihenfolge und neues Vorkommen auf beiden, kein Schwarzbild. |
| R14 | B/C/D · Rückkehr aus der Szene | Auf beiden reagiert die eigene Figur auf Bewegung und Kamera. Kein unbeabsichtigtes Pausemenü. |
| R15 | A/B · Netzwerk und Trace | Lobbybindung bleibt konsistent. Im Gameplay folgt die Partnerspur dem anderen Spieler. |
| R16 | Alle · Integrität der Originalstände | Vorher/Nachher-Hashes der privaten Testoriginale stimmen überein, Wiederherstellung geprüft. |
| R17 | B · Kampagne erneut starten | Neuer Versuch erhält eigene IDs, keine alte Pause/Freigabe wird übernommen. |
| R18 | A/C · Einzelspieler mit inaktivem Koop | Titelmenü, native Eingabe und im isolierten Lauf die native Szenenwiedergabe funktionieren. |

Für die Endabnahme drei aufeinanderfolgende vollständige Läufe mit demselben Archiv protokollieren. Ein Buildwechsel beginnt eine neue Serie. Pro Lauf Schritt, Ergebnis beider Spieler und zugehörigen Ausschnitt der Zeitleiste zuordnen. Ein fehlgeschlagener Zwischenlauf unterbricht die Serie.
