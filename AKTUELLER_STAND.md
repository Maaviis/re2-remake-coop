# Aktueller Stand – RE2 Remake Koop

Stand: 15. November 2026.

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
- **Laden und Inventar:** Der erlaubte alte Spielstand wurde kontrolliert
  geladen; Ladekopf und Inventar-Teilwerte wurden anschließend aus dem
  laufenden Spiel gelesen. Gemeinsames Laden und Speichern fehlen.
- **Pause:** Die native Pausenprobe hielt die beobachtete Animation sowie
  tatsächliche Spiel-/Rekord-/Szenenzeiten an und kehrte vollständig aus dem
  Pausenmenü zurück. KI, Physik, alle Skripte und Cutscenes sind damit
  noch nicht als angehalten nachgewiesen.

## Was mit den Pull Requests passiert ist

[PR #62](https://github.com/Maaviis/re2-remake-coop/pull/62) wurde von
bySenom nach `main` zusammengeführt. Er enthält die 54 ursprünglichen
PR-Stände #8 bis #61 sowie die späteren Menü-/Einladungsänderungen aus
#63 und #67. Die ursprünglichen Kopfcommits wurden über die Git-Historie
abgeglichen. Die 29 danach noch offenen Stapel-PRs wurden mit Verweis auf
diese Integration geschlossen; ihre Entwicklungsbranches bleiben erhalten.

146 Python-Tests und 15 Lua-Einstiegssuiten bestehen im gemeinsamen
Prüfstand einschließlich #68. Die Lobby-Suite führt zusätzlich den separaten Menücheck aus.
Das native Windows-Plugin wird ebenfalls gebaut und mit zwei CTests geprüft.
[INTEGRATION_REVIEW.md](INTEGRATION_REVIEW.md) beschreibt Nachweise und Grenzen.

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
