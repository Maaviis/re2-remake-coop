# Nachrichtenschema für RE2-Koop, Entwurf v1

Das Schema beschreibt die Nachrichten zwischen Spieladapter, Host und Replik.
`v1.py` ist die ausführbare Referenz für die Strukturprüfung. Die
[Testvektoren](v1-examples.json) enthalten eine Spielerpose, eine Tür, ein
Kampagnenskript, eine Zwischensequenz sowie Snapshots vor und nach den Ereignissen.

## Nachrichten

Eine Nachricht ist genau ein UTF-8-JSON-Objekt. `version` ist die Ganzzahl `1`.
Doppelte Objektschlüssel und nicht endliche Zahlen werden verworfen.
Ganzzahlen in Nachrichten liegen zwischen `-(2^53 - 1)` und `2^53 - 1`, damit
auch Leser mit IEEE-754-Binär64 alle zulässigen Ganzzahlen exakt darstellen
können. Die folgende Tabelle listet alle zulässigen Felder neben `version` und `type`.

| `type` | Richtung | Felder |
| --- | --- | --- |
| `hello` | Host ↔ Gast | keine weiteren Felder |
| `propose` | Beobachter → Host | `kind`, `target`, `value` |
| `event` | Host → Replik | `data` mit `kind`, `target`, `value`, `session_id`, `sequence` und `digest` |
| `snapshot` | Host → Replik | `data` mit `state`, `session_id`, `sequence` und `digest` |
| `error` | Host → Absender | `message` als nicht leerer Text |

`kind` ist einer der folgenden Werte. Die Tabelle nennt die zugehörige
Zustandstabelle im Snapshot.

| Kategorie | Ereignis → Snapshot-Feld |
| --- | --- |
| Spieler und Kampf | `player` → `players`, `action` → `actions`, `damage` → `damage`, `enemy` → `enemies` |
| Welt | `door` → `doors`, `puzzle` → `puzzles`, `item` → `items`, `inventory` → `inventories` |
| Kampagne | `flag` → `flags`, `script` → `scripts`, `cutscene` → `cutscene` |

`target` ist eine nicht leere Objekt-ID als String. Bei `cutscene` ist `target`
`null`, weil der Zustand nur eine aktive Zwischensequenz pro Sitzung führt.
`value` ist ein JSON-Wert. Die für diese Version kompatiblen Spielwerte sind in
den Testvektoren sichtbar. Weitere Felder und Validierungen pro Spielereignis
werden mit der jeweiligen Engine-Anbindung festgelegt.

Ein Snapshot enthält alle elf Felder unter `state`. Mit Ausnahme von `cutscene`
ist jedes Feld ein Objekt, dessen Schlüssel die Objekt-IDs sind. Leere Tabellen
werden als `{}` geschrieben. `cutscene` enthält den aktuellen JSON-Wert oder
`null`. Eine `session_id` ist ein nicht leerer, vom Host vergebener String.
Sequenzen sind Ganzzahlen bis `2^53 - 1`. Der initiale Snapshot darf Sequenz `0`
haben. Das erste Ereignis einer Sitzung hat Sequenz `1`.

## Autorität und Wiederherstellung

- Nur der Host vergibt `session_id` und `sequence` für verbindliche Änderungen.
  Der Host validiert die Rolle des Absenders und die Spielaktion vor der
  Übernahme. Der Strukturtest allein belegt keine Berechtigung.
- `digest` ist der kleingeschriebene hexadezimale SHA-256-Prüfwert des vollständigen
  Zustands nach dem Ereignis bzw. im Snapshot. Für diesen Entwurf ist
  `sync_model.state_digest` die Referenz. Die Eingabe ist UTF-8 ohne BOM,
  Objektschlüssel sind rekursiv sortiert, es gibt keine optionalen Leerzeichen,
  und Nicht-ASCII-Zeichen werden direkt geschrieben. Andere Implementierungen
  müssen die kanonische Zahlendarstellung der Referenz reproduzieren. Bei
  Prüfsummen sind `1` und `1.0` verschiedene Werte. Gleitkommazahlen behalten
  das Vorzeichen von `-0.0`. Der Vektor `canonical_reconnect_state_utf8` liefert
  die exakten UTF-8-Eingabebytes, einschließlich `1e-07`. Der Codec prüft die
  Form des Prüfsummenfelds. `Replica.apply` und `Replica.restore` prüfen den
  tatsächlichen Zustandswert.
- Eine Replik übernimmt zuerst einen Snapshot und dann Ereignisse derselben
  Sitzung in aufsteigender Reihenfolge. Bereits übernommene Sequenzen werden
  ignoriert. Eine Lücke oder ein Prüfsummenfehler erfordert einen neueren oder
  gleich aktuellen Host-Snapshot, bevor weitere Ereignisse übernommen werden.
- Der Engine-Adapter verwendet die zwischen beiden Instanzen vereinbarten
  Objekt-IDs. Speicheradressen und lokal erzeugte Objektreferenzen dienen nur
  zur Zuordnung im eigenen Prozess. Beim Anwenden von Host-Ereignissen hält
  der Adapter deren Herkunft fest, damit beobachtete Folgeänderungen nicht
  erneut als lokale Vorschläge an den Host gehen.

## Migration des Loopback-Prototyps

Der Loopback-CLI verwendet standardmäßig den unversionierten Modus 0. Für
einen v1-Test starten Host und Gast jeweils mit `--protocol-version 1`.

~~~sh
python wire.py host --port 45678 --protocol-version 1
python wire.py client --port 45678 --protocol-version 1
~~~

Der Host sendet zuerst `{"version":1,"type":"hello"}`. Der Gast prüft die
Version und antwortet mit derselben Nachricht. Erst dann sendet der Host einen
Snapshot und registriert den Gast für Ereignisse. Bei einer unpassenden
Version oder einer anderen ersten Nachricht bricht die Verbindung ab. Ein
Host-Handshake endet auch, wenn ein Gast fünf Sekunden lang keine Daten
liefert. Der Versionsabgleich prüft ausschließlich die Formatkompatibilität.

Die Hülle ergänzt `version`. Vorschläge werden mit explizitem `target` und
`value` serialisiert. Für Vorschläge ohne Ziel wie `cutscene` ist `target` `null`.

Der Codec verarbeitet einzelne Nachrichten. Die TCP-Schicht schließt jede
v1-Nachricht mit LF ab und akzeptiert beim Lesen höchstens 1 MiB pro Zeile.
Die REFramework-Beobachterdatei aus PR #9 ist die lokale Eingabe des
Spieladapters. Dessen bestehender Sender verwendet Modus 0.

Im Repository-Verzeichnis `python -m unittest discover -s tests -v` ausführen.
Der Kompatibilitätstest vergleicht die Beispielnachrichten mit dem vorhandenen
Host und spielt sie über den Codec auf eine Replik. Der finale Snapshot wird
auch in einer neu verbundenen Replik wiederhergestellt.
