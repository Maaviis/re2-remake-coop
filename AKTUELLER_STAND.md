# Aktueller Stand – RE2 Remake Koop

Stand: 20. November 2026.

**Eine Kampagne zu zweit ist noch nicht spielbar.** Es gibt inzwischen
mehrere im Spiel geprüfte Bausteine. Die vollständige Synchronisation
von Gegnern, Gegenständen, Fortschritt und allen Zwischensequenzen fehlt.

## Was bereits funktioniert beziehungsweise geprüft wurde

- **Menü und Lobby:** Der native Hauptmenüeintrag „Multiplayer“, die
  Rückkehr mit Zurück/Esc und wiederholtes Öffnen wurden in einer
  Spielinstanz geprüft. Private Steam-Lobbys lassen sich erstellen.
  Der Code enthält außerdem die Bestätigung einer aktuellen Einladung.
  Ein lesender Menücheck prüft vorab Dateistand, frische Eingabetelemetrie,
  Prozess, Rolle und Lobbyzustand (#68, nach ausdrücklicher Freigabe gemergt).
  Ein erfolgreicher Beitritt mit zwei echten Steam-Konten steht aus.
- **Spielerbeobachtung:** Position, Drehung und ausgewählte Animationsdaten
  lassen sich lesen und übertragen. Ein eigenes Testobjekt kann eine Pose
  beziehungsweise einen unterstützten Idle-Clip darstellen. Ein vollständiger
  zweiter Spieler mit Kampf und Interaktion ist damit noch nicht vorhanden.
- **Laden und Inventar:** Ein geschütztes Testpaket hat einen freigegebenen
  alten Spielstand in RE2 geladen. Ladekopf und Inventar-Teilwerte wurden
  aus der laufenden Szene gelesen. Der vorbereitete Paketstart bestätigte
  die Abweisung ohne Gast. Gemeinsames Laden und Speichern bleiben offen.
- **Pause:** Die native Pausenprobe hielt die beobachtete Animation sowie
  tatsächliche Spiel-/Rekord-/Szenenzeiten an und kehrte vollständig aus dem
  Pausenmenü zurück. KI, Physik, alle Skripte und Cutscenes sind damit
  noch nicht als angehalten nachgewiesen.

- **Gegnerdaten:** 55 registrierte und 87 separat gespeicherte Datensätze
  sind bestätigt. In einer echten Instanz wurden fünf aktive Controller,
  die native HP-Folge 770 → 769 → 0 und dieselbe GUID nach Aus-/Einstreamen
  an neuen Controller-/HP-Objekten gemessen. Der Killzähler blieb 19;
  reguläre Treffer-/Todesnebenwirkungen und die zweite Spielwelt sind
  weiter erforderlich. Die spätere Ladebindung aus #87 verlängert die
  laufende Beobachtung über die ursprüngliche 120-Sekunden-Grenze.
  [Details](ENEMY_WITNESS.md)

## Was mit den Pull Requests passiert ist

[PR #62](https://github.com/Maaviis/re2-remake-coop/pull/62) wurde von
bySenom nach `main` zusammengeführt. Er enthält die 54 ursprünglichen
PR-Stände #8 bis #61 sowie die späteren Menü-/Einladungsänderungen aus
#63 und #67. Die ursprünglichen Kopfcommits wurden über die Git-Historie
abgeglichen. Die 29 danach noch offenen Stapel-PRs wurden mit Verweis auf
diese Integration geschlossen; ihre Entwicklungsbranches bleiben erhalten.

Der neue Kandidat für `main` enthält die 43 geprüften PR-Köpfe #70–85,
#87–108, #117, #120, #122, #123 und #125. Er bündelt Menü, Lobby, Pose,
Gegnerdiagnose, Speicherschutz, vorbereiteten Ladepfad und den gemeinsamen
CI-Download. Die zusätzlichen Treffer-, Todes-, KI- und Timeline-Beobachter
sind lokale Diagnosen, die gezielt gestartet werden. Die Entwürfe #109–115
bilden eine eigene Versuchsreihe für den nativen Steam-Lesepfad und private
Ladeantworten. Der Spieltest mit zwei Steam-Konten steht noch aus.
[INTEGRATION_REVIEW.md](INTEGRATION_REVIEW.md) beschreibt die frühere Integration
nach #62. [STATUS.md](STATUS.md) führt die Nachweise des neuen Entwurfs.

## Die nächsten Arbeitspakete

1. **Welt und Kampf:** echte Gegner-, Treffer-, Todes-, Item-, Tür- und
   Rätselereignisse erfassen und in beiden Welten anwenden.
2. **Kampagne:** Fortschrittsflags, Skriptfolgen und jede Cutscene mit
   Beginn, Ablauf, Skip und Ende anbinden.
3. **Laden und Wiederverbindung:** beide Welten sicher anhalten, den
   vollständigen Zustand übertragen/anwenden und gemeinsam freigeben.
   Gemeinsames Speichern gehört ebenfalls dazu.
4. **Zwei echte Instanzen:** jede Kategorie mit zwei PCs und zwei
   Steam-Konten prüfen. Der zweite PC ist laut bisherigem Nutzerstand
   noch nicht verfügbar.

[PLAN.md](PLAN.md) ordnet diese Aufgaben den Fachbereichen zu.
[STATUS.md](STATUS.md) führt die technischen Prüfgrenzen. Die Übernahme
von Quellcode installiert keine neue Fassung in der normalen Spielinstallation.
Lokale Spieltests verwenden weiterhin ausschließlich die freigegebenen
Spielstände vom 11.11.2026 und Terminalsteuerung.
