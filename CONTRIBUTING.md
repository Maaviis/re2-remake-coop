# Mitwirken

Den aktuellen Projektstand findest du in der [README](README.md). Größere Änderungen an Engine, Netzwerk oder Spielständen werden vorab im zugehörigen Issue abgestimmt.

## Entwicklungsablauf

1. Vom aktuellen `main` ausgehen. Kurzlebige Branches nutzen, wenn parallele Arbeit eine getrennte Änderung braucht.
2. Schnittstellenänderungen mit Beispielnachricht und Protokollversion beschreiben.
3. `python -m unittest discover -s tests -v` im Repository-Verzeichnis ausführen.
4. Bei Spielcode die RE2- und REFramework-Version sowie Testschritte mit zwei Instanzen dokumentieren. Ein Einzelinstanz-Test ist als solcher zu kennzeichnen.
5. Die geprüfte Änderung auf `main` integrieren. Bei einem Pull Request `main` als Ziel verwenden.
6. Für die offene Spielabnahme ein Issue mit Build, konkreten Testschritten und Sollverhalten anlegen.

Keine Dateien aus der installierten Fremdmod übernehmen oder verändern. Keine Spielpakete, DLLs, Steam-Dateien, Speicherstände oder persönlichen Logs committen. Vertrauliche Zugangsdaten gehören nie in Issues oder Pull Requests.

## Definition für einen Merge

Der Code lässt sich in einer sauberen Umgebung reproduzieren, die Protokolltests bestehen, die betroffenen Schnittstellen sind dokumentiert und die tatsächliche Prüfgrenze ist klar benannt. Die Integration entscheidet bei Änderungen am gemeinsamen Nachrichtenformat.
