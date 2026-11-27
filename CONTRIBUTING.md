# Mitwirken

Den aktuellen Projektstand findest du in der [README](README.md). Größere Änderungen an Engine, Netzwerk oder Spielständen werden vorab im zugehörigen Issue abgestimmt.

## Entwicklungsablauf

1. Vom aktuellen `main` ausgehen. Kurzlebige Branches nutzen, wenn parallele Arbeit eine getrennte Änderung braucht.
2. Schnittstellenänderungen mit Beispielnachricht und Protokollversion beschreiben.
3. `python tools/run_tests.py` im Repository-Verzeichnis ausführen.
4. Bei Spielcode die RE2- und REFramework-Version sowie Testschritte mit zwei Instanzen dokumentieren. Ein Einzelinstanz-Test ist als solcher zu kennzeichnen.
5. Die geprüfte Änderung auf `main` integrieren. Bei einem Pull Request `main` als Ziel verwenden.
6. Für die offene Spielabnahme ein Issue mit Build, konkreten Testschritten und Sollverhalten anlegen.

Nach der Integration den eigenen kurzlebigen Remote-Branch entfernen, sobald sein letzter Commit in `main` enthalten ist. Vorher den aktuellen Remote-Stand und die Köpfe und Ziele offener PRs prüfen. Geschützte Branches und Branches mit abhängiger Arbeit bleiben erhalten.

Keine Dateien aus der installierten Fremdmod übernehmen oder verändern. Keine Spielpakete, DLLs, Steam-Dateien, Speicherstände oder persönlichen Logs committen. Vertrauliche Zugangsdaten gehören nie in Issues oder Pull Requests.

## Definition für einen Merge

Der Code lässt sich in einer sauberen Umgebung reproduzieren, die Protokolltests bestehen, die betroffenen Schnittstellen sind dokumentiert und die tatsächliche Prüfgrenze ist klar benannt. Die Integration entscheidet bei Änderungen am gemeinsamen Nachrichtenformat.

## Ablage im Repository

| Inhalt | Verzeichnis |
| --- | --- |
| Python-Laufzeit der Steam-Bridge und Nachrichtenprotokoll | `bridge/`, `bridge/protocol/` |
| REFramework-Skripte und native Windows-Plugins | `reframework/`, `network/` |
| Technische Anleitungen und Entwicklungsnotizen | [docs/](docs/README.md), nach Thema |
| Automatisierte Tests und versionierte Messbelege | `tests/`, `validation/` |
| Entwicklerwerkzeuge, Paketbau und Startskripte | `tools/`, `scripts/` |

Der Paketbau legt die Bridge-Module im installierten `re2-coop/` ab. Startbeispiele aus dem Quellbaum verwenden `python bridge/<skript>.py`. Für einen einzelnen Python-Test funktioniert etwa `python tools/run_tests.py tests.test_lobby_sync`. Persönliche Laufzeitdaten und fertige ZIPs liegen außerhalb des Checkouts.
