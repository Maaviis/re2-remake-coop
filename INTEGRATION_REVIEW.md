# Integrationsabgleich nach PR #62

Prüfstand: `main` bei `0ae8b2b2400acfc147bb58fc69a4639f97708951`,
15. November 2026. [PR #62](https://github.com/Maaviis/re2-remake-coop/pull/62)
wurde von bySenom zusammengeführt. Dieser Folgebeitrag übernimmt den
bereits veröffentlichten Stand als Grundlage.

## Historie und PR-Bereinigung

Die 53 ursprünglich geprüften Kopfcommits aus #8 bis #60 sind sämtlich
Vorfahren dieses `main`-Stands. Zusätzlich enthält er #61, die aktuelle
Einladungsbestätigung aus #63 und die Menü-Eingabekorrekturen aus #67.
Die Abstammung aller 29 nach dem Merge noch offenen PR-Kopfstände wurde
ebenfalls einzeln geprüft. Sie wurden anschließend mit dem jeweiligen
Kopfcommit und einem Verweis auf #62 geschlossen.

GitHub ließ eine nachträgliche Änderung ihres Zielbranches auf `main`
nicht zu, weil dort bereits alle Commits enthalten waren. Deshalb wurde
der offene Stapelzustand bereinigt. Eine Schließung ist kein zusätzlicher
Code-Merge und keine Gameplay-Abnahme. Die ursprünglichen Branches und
die Autorenhistorie bleiben erhalten.

Die lokale, parallel vorbereitete ältere Integration wurde nicht über
den neueren gemeinsamen Stand veröffentlicht. Insbesondere bleiben die
späteren Änderungen an Lobby-Erstellung, Einladungsrevision, Mauszeiger,
Esc und wiederholter Hauptmenüauswahl erhalten. Die Quelltexte der
Einzelproben aus #11, #22 und #23 sowie ihre Tests sind vorhanden.

## Menü-Vorprüfung aus #68

Der anschließend eingegangene und nach ausdrücklicher Nutzerfreigabe
gemergte PR #68 ergänzt einen lesenden Menümodus
des Steam-Preflights. Er vergleicht installierte Skripte und Plugin,
frische Eingabetelemetrie sowie Prozess-ID, Bridge-Rolle und lokalen
Lobbyzustand. Der vorhandene Posenmodus mit Peer-Roundtrip bleibt getrennt.
Die PID ist lokaler Status und kein neues Netzwerkformat. Drei zusätzliche
Python-Tests prüfen beide Rollen, fehlende/veraltete/fremde Berichte und
abweichende Skripte. Der Einzelinstanz-Nachweis des Autors ist in
STEAM_POSE_TEST.md dokumentiert; zwei Konten bleiben erforderlich.

## Automatische Prüfungen

- 146 Python-Tests und 15 Lua-Einstiegssuiten gehören zum konsolidierten
  Stand. `test_lobby_lua.lua` ruft zusätzlich `check_main_menu_lua.lua` auf;
  es sind 16 unterschiedliche Lua-Prüfdateien.
- Der [main-Testlauf nach #62](https://github.com/Maaviis/re2-remake-coop/actions/runs/43761478963)
  bestand mit Python und Lua.
- Der Folgeworkflow findet `tests/test*.lua` automatisch und ergänzt
  einen getrennten Windows-x64-Build mit beiden nativen CTests.
- Externe Build-Header sind auf REFramework
  `d1461375aee4ec3f313170f8eaad12064eb542d9` und Source SDK
  `e1f1fd42271805072f052051c26c21caa2c87b04` festgelegt.
  Spiel-/Steam-Binärdateien, Speicherstände und persönliche Logs werden
  dafür nicht ins Repository aufgenommen.

## Native Nachweise und offene Grenzen

Die früheren Einzelinstanz-Nachweise für kontrolliertes Laden,
Inventar-Teilwerte und Gameplay-Pause bleiben in den jeweiligen
Fachdokumenten erhalten. Der Autor von #62 dokumentiert außerdem den
nativen Lobby-Erstellungszyklus und den Menütest mit drei Öffnungen,
Zurück/Esc und anschließender Originaloption. Das sind getrennt
zugeordnete Einzelinstanz-Nachweise, keine gemeinsame Kampagne.

Vollständige Welt-/Kampf-/Story-/Cutscene-Anbindung, portable native
Zustandsanwendung, gemeinsame Ladebarriere, gemeinsames Speichern und
Wiederherstellen sowie sämtliche Zwei-Instanzen-Abnahmen fehlen.
Auch der frühere Absturz nach einer abgefangenen Fortsetzen-Anforderung
ist durch die Integration nicht als behoben nachgewiesen.

Die Konsolidierung schließt keinen Gameplay-Meilenstein ab.
Der verständliche Überblick steht in [AKTUELLER_STAND.md](AKTUELLER_STAND.md),
die nächste Arbeitsteilung in [PLAN.md](PLAN.md).
