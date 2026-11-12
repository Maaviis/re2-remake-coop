# Mitwirken

Dieses Projekt befindet sich in einer frühen Forschungsphase. Bitte übernimm ein Arbeitspaket aus [PLAN.md](PLAN.md) in einem Issue, bevor du die Engine- oder Netzwerk-Schnittstelle änderst. Die Rollen sind noch nicht personell vergeben.

## Entwicklungsablauf

1. Eigenen Branch für eine klar begrenzte Aufgabe erstellen.
2. Schnittstellenänderungen mit Beispielnachricht und Protokollversion beschreiben.
3. `python -m unittest discover -s tests -v` im Repository-Verzeichnis ausführen.
4. Bei Spielcode die RE2- und REFramework-Version sowie Testschritte mit zwei Instanzen dokumentieren. Ein Einzelinstanz-Test ist als solcher zu kennzeichnen.
5. Pull Request mit Bezug auf die betreffende Zeile in [STATUS.md](STATUS.md) eröffnen.

Keine Dateien aus der installierten Fremdmod übernehmen oder verändern. Keine Spielpakete, DLLs, Steam-Dateien, Speicherstände oder persönlichen Logs committen. Vertrauliche Zugangsdaten gehören nie in Issues oder Pull Requests.

## Definition für einen Merge

Der Code lässt sich in einer sauberen Umgebung reproduzieren, die Protokolltests bestehen, die betroffenen Schnittstellen sind dokumentiert und die tatsächliche Prüfgrenze ist klar benannt. Die Integration entscheidet bei Änderungen am gemeinsamen Nachrichtenformat.
