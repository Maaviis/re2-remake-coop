# Gemeinsame Zwischensequenzen und Einzeltest

Ein Spieler wartet am Einstieg. Erreicht der zweite dieselbe Zwischensequenz derselben Kampagne, starten beide automatisch. Ein Skip-Wunsch braucht die Bestätigung des Partners. Bei Ablehnung läuft die Szene weiter. Erste Abnahmefälle sind der Trucker, Leon im Auto und das erste Betreten des Tankstellenshops.

1. Die Pose-Bridge tauscht Ereigniskennung, Auftreten und Entscheidung innerhalb des vereinbarten Kampagnenstarts aus. Ein anderer Startversuch, eine unterbrochene Verbindung oder eine alte Antwort darf keine Wiedergabe freigeben.
2. Die Lua-Anbindung prüft die vorgefundenen nativen Film- und Timeline-Methoden. Ein Startversuch darf die Story genau einmal weiterführen. Skip und Ablehnung gehören zum aktuellen Ereignis und zur aktuellen Anfrage.
3. Ein ausdrücklich gestarteter Einzeltest verwendet einen lokalen Gast und den geschützten Koop-Speicherordner einer leeren Host-Lobby. Ankunft und Skip-Verhalten lassen sich am selben PC auslösen. Ein echter Mitspieler beendet die Simulation. Der Einzeltest erzeugt keine Steam-Mitgliedschaft oder gegenseitige Kampagnenfreigabe.
4. Für die Mitspielerfigur werden die vorhandene Kampagnenfreigabe, Positionsdaten und der bestehende Avatar-Renderer geprüft. Im Einzeltest darf die Vorschau ihre Bewegung von der lokalen Figur ableiten.
5. Tests prüfen Reihenfolge, doppelte Zustellung, Ablehnung, Verbindungswechsel und Einzelbetrieb. Das aus dem Commit gebaute Steam-ZIP wird auf seine Laufzeitmodule geprüft. Der Zwei-PC-Test vergleicht Start und Skip an jeder der drei Szenen sowie die sichtbare Figur auf beiden PCs.
