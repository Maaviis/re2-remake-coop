# Gemeinsame Spielstand-Vorprüfung

Dieser Entwurf verbindet die lokale native Spielstandauswahl mit einer
Bestätigung durch beide Steam-Bridge-Teilnehmer. Er ist die Vorstufe der
gemeinsamen Ladebarriere. **Er lädt und speichert nichts, startet keine
Kampagne und gibt keine Gameplay-Synchronisation frei.**

Der bisherige `save_ref.metadata_digest` deckt nur die Katalog-Metadaten
ab. Gleicher Slot, Zeitpunkt und Text sind kein Nachweis gleicher
Speicherdateien. Die neue ausdrücklich aktivierte Prüfung liest deshalb
die tatsächlich lokal vorhandenen Dateibytes auf beiden Rechnern.

## Ablauf

1. Host und Gast verwenden dieselbe Bridge-Fassung, einen frischen
   lokalen nativen Katalog und ein ausdrücklich angegebenes Datum.
   Der Host wählt einen verfügbaren nativen Slot. Beide melden sich
   für dieselbe Lobby-Revision bereit.
2. Der Host fordert `check-load` an. Seine Bridge validiert den aktuellen
   lokalen Katalogverweis und berechnet SHA-256 über die passende Datei.
   Sie veröffentlicht einen neuen zufälligen Versuch mit Sitzungskennung,
   Revision und Dateidigest im autoritativen Lobbyzustand.
3. Die Gast-Bridge löst diesen Slot ausschließlich in ihrem eigenen
   angegebenen Speicherordner auf. Modus, Slot, Zeitwert und Szenario
   müssen im eigenen datumsgefilterten Katalog passen. Lokalisierte
   Anzeigetexte müssen nicht gleich sein. Danach vergleicht sie die Datei.
4. Der Host übernimmt nur eine Bestätigung für die aktuelle Sitzung,
   Revision und Versuch-ID mit höherer Bestätigungssequenz. Bei passendem
   Dateidigest wird `load_check.phase` zu `prepared`. Das bedeutet nur:
   Beide lokalen Prüfpfade haben gleiche Dateibytes bestätigt.
5. Beide Seiten lesen die Quellen weiter. Der Gast sendet im Abstand von
   einer Sekunde eine neue Bestätigung; nur neue Sequenzen verlängern
   die Fünf-Sekunden-Frist auf der lokalen monotonen Host-Uhr. Es werden
   keine Rechneruhren verglichen. Der Host prüft seine eigene Datei
   ebenfalls mindestens einmal je Sekunde bei laufender Bridge-Schleife.
   Der Gast verlangt einen verifizierten Lobbyzustand aus den letzten
   drei Sekunden. Bei Ablauf blendet er die alte Vorprüfung aus, setzt
   die Bestätigungen aus und nimmt seine Bereitschaft für die letzte
   geprüfte Revision zurück. Steam-Posen und Heartbeats können dabei
   weiterlaufen. Der Gast kann sich nach einem frischen Lobbyzustand
   erneut bereit melden.
6. Quellenverlust, abweichende Bytes, neue Auswahl/Einstellungen,
   zurückgenommene Bereitschaft, Verbindungswechsel oder Fristablauf
   machen den Versuch ungültig. Ein fehlgeschlagener Versuch bleibt
   fehlgeschlagen; eine verspätete Bestätigung kann ihn nicht beleben.
   Eine neue Prüfung erhält eine neue Versuch-ID.

Die Dateien werden ausschließlich lesend geöffnet. Der Dateiname entsteht
lokal aus dem validierten Slot (`dataNNNSlot.bin`); eine Netzwerknachricht
liefert keinen Pfad. Der Ordner muss absolut sein. Symlinks, ein Ziel
außerhalb dieses Ordners, leere Dateien und Dateien über 32 MiB werden
abgewiesen. Dateiidentität, Größe und Änderungszeit werden vor/nach dem
Lesen geprüft, die Katalogidentität danach erneut. Ein Lese-/Metadatenfehler
liefert keinen erfolgreichen Digest. Das ersetzt keine Betriebssystemsperre
für einen späteren nativen Ladevorgang.

## Entwicklerbedienung

Nur in den bereits dokumentierten isolierten Testinstallationen verwenden.
Beide benötigen den Exporter `re2_coop_save_catalog.lua`. Das optionale
Argument bezeichnet jeweils den eigenen nativen `win64_save`-Ordner;
keine Speicherdatei wird kopiert oder übertragen.
Beim Gast verwendet die Bereitschaftsprüfung automatisch den Katalog
dieser Dateiquelle. Ohne Dateivorprüfung kann der Gast seinen Katalog
weiterhin ausdrücklich mit `--save-catalog` aktivieren.

```powershell
# Host, zusätzlich zu seiner vorhandenen Steam-Lobby:
python steam_pose_bridge.py --role host --pid $re2Pid --data "<RE2>/reframework/data" --lobby --save-catalog --lobby-save-slot scenario:4 --allow-save-date 2026-11-11 --load-save-directory "<eigener nativer win64_save-Ordner>"
# Gast, auf dessen Rechner mit dessen RE2-Prozess:
python steam_pose_bridge.py --role guest --pid $re2Pid --data "<RE2>/reframework/data" --lobby --allow-save-date 2026-11-11 --load-save-directory "<eigener nativer win64_save-Ordner>"
# Auf beiden Seiten nach bestätigter Auswahl:
python lobby_control.py --data "<RE2>/reframework/data" ready yes
# Nur der Host:
python lobby_control.py --data "<RE2>/reframework/data" check-load
python lobby_control.py --data "<RE2>/reframework/data" status
python lobby_control.py --data "<RE2>/reframework/data" cancel-load-check
```

Ein Terminalbefehl bestätigt nur das Schreiben einer lokalen Anweisung.
Das autoritative Ergebnis steht unter `lobby.data.load_check`; auch
`fresh`, `connected`, Sitzung, Revision und Bereitschaft prüfen.
Ohne `--load-save-directory` ist diese Funktion deaktiviert. Ein Gast
ohne diese ausdrückliche Aktivierung bestätigt keine Datei; der
Hostversuch läuft ab. Diese Entwicklerfunktion hat noch keinen
zusätzlichen Knopf im Spielmenü.

## Nachweise und offene Grenzen

Die Python-Prüfungen verwenden synthetische Dateien. Zwei laufende
Bridge-Schleifen mit getrennten Daten-/Speicherordnern bestätigen gleiche
Bytes und verwerfen eine geänderte Gastdatei bei unveränderten Metadaten.
Weitere Fälle prüfen Sitzungs-/Revisionswechsel, Wiederbeitritt, alte
Versuche, fehlende/ungültige Quellen, Dateiänderung während des Lesens,
Abbruch, neue gegenüber doppelten Bestätigungen und lokale Fristen.
Sie rufen keine native Lade-/Speicherfunktion auf.

Der kombinierte Stand enthält außerdem drei abgegrenzte Beiträge von
bySenom, ohne deren ursprüngliche PRs zu mergen:

| Beitrag | Herkunft | Integration |
|---|---|---|
| Laufende Slotfreigabe vor überlappenden Befehlen schützen; Befehls-, Policy- und Lade-ID trennen | [#52, 7e54fc3](https://github.com/Maaviis/re2-remake-coop/commit/7e54fc39c44b5d97f9b476ab87deec4a73c2a6a3) | Einzelpatch auf #51 übernommen |
| Terminal wartet mit `--wait` auf die eigene native Befehls-/Lade-ID | [#53, f350f59](https://github.com/Maaviis/re2-remake-coop/commit/f350f598d437311b7ea181d55f8bf08f90ddc453) | Auf #52 aufgebaut; Einzelpatch übernommen |
| Lokaler Gastkatalog, Identitätsdigest, automatische Bereitschaftsrücknahme und Menühinweis | [#55, dec7f62](https://github.com/Maaviis/re2-remake-coop/commit/dec7f62ef870f0fa52551ab5d81b2f1a1b5c256f) | Mit Dateivorprüfung kombiniert; Gastkatalog der Dateiquelle wiederverwendet |

123 Python-Tests und zehn Lua-Suiten bestehen im gemeinsamen Stand.
Zusätzlich wurde die Dateianbindung am 15. November 2026 in einer frischen
RE2-Instanz (Build 11636119, REFramework d1461375, TDB 70) gegen den
echten Katalog geprüft: Die freigegebene Datei vom 11.11.2026 ergab
wiederholt denselben SHA-256-Wert wie die geprüfte Sicherung; die neuere
Auswahl wurde vor dem Dateizugriff abgewiesen. Es gab keine Kampagnen-
Ladeanforderung, Tastatur-/Mauseingabe oder Bildschirmaufnahme. Nach
bestätigtem Prozessende wurden Originaldateien zurückgestellt; alle zwölf
Speicherdateien blieben bytegleich, keine neue erschien. Das bestätigt nur
die lokale Katalog-/Dateianbindung, keinen gemeinsamen Steam-Lauf.
Die zusätzlich übernommenen Befehls-/Lade-IDs, `--wait` und die native
Gast-Menüanzeige haben hier noch keinen gemeinsamen nativen Abnahmelauf.

Die Datei kann verschlüsselte oder kontogebundene Daten enthalten.
Gleiche Bytes beweisen weder die Nutzbarkeit unter einem anderen
Steam-Konto noch den gleichen bereits laufenden Weltzustand. Verschiedene
Bytes könnten umgekehrt denselben logischen Fortschritt darstellen;
dieser Entwurf verweigert dann die Bestätigung. Er entschlüsselt und
portiert nichts. Zwei echte Konten/Spielinstanzen und ein portabler
nativer Zustandsnachweis fehlen weiterhin. Private Pfade, Digests,
Speicherdateien und Testprotokolle gehören nicht ins öffentliche Repo.

Für die eigentliche Ladebarriere fehlen: an diesen Versuch gebundene
einmalige native Ladeanforderungen, der bestätigte Kampagnenmenüabschluss,
native Fehlerbehandlung, Stillhalten beider Welten während des Übergangs,
passende Szenen-/Spielerzeugen und der vollständige gemeinsame
Welt-/Inventar-/Fortschritts-Snapshot vor der Spielfreigabe. Der offene
Absturz aus [READONLY_LOAD.md](READONLY_LOAD.md) ist nicht behoben.
Gemeinsames Speichern, Rejoin und sämtliche Synchronisationskategorien
aus [STATUS.md](STATUS.md) bleiben Teil des Ziels.
