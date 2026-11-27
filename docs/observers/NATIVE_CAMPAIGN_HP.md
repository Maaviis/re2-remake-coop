# Positive HP-Anwendung an einem Kampagnengegner

Am 17. November 2026 wurde der unveränderte positive HP-Adapter
`re2_coop/guest_enemy_hp.lua` erstmals in dieser Testreihe an einem echten
Kampagnengegner bestätigt. Bisher war der Setter nur an einer eigenen
HP-Testkomponente im Titelbild positiv geprüft. Dieser Lauf ergänzt einen
lokalen Engine-Nachweis; er bestätigt keine Verbindung zweier Spielinstanzen.

## Aufbau

Verwendet wurden RE2 Build 11636119, REFramework d1461375/TDB 70 und die
installierte geschützte Runtime `4494ef2`. Deren HP-Adapter blieb unverändert.
Die vererbten Windows-Dateisperren wurden vor dem Spielstart erworben und
die native Steam-Schreibsperre blieb aktiv. Die eigenen Diagnose- und
Bewegungshelfer lagen nur vorübergehend in der Testinstallation.

Es wurde ausschließlich der freigegebene alte Slot 4 vom 11.11.2026 geladen.
Die eigene Figur ging über den bereits untersuchten Treppenweg bis zum
oberen Raum. Es gab weder Teleportation noch Änderungen an Storyflags.
Jede kurze Bewegung verlangte aktuelle Schutzbelege, dieselbe Lade-ID und
dieselben Spieler-/Szenenobjekte. Am Ziel waren fünf Gegnercontroller aktiv.
Der ausgewählte lebende Zombie hatte `kind_id=0`, `inherit_id=-1`, 770 HP,
Default-HP 770 und keinen aktiven `NoDamage`-Schutz.

Die Hostquelle war **ausdrücklich lokal erzeugt**. Der vorhandene
`GuestEnemyFile` veröffentlichte nach frischer nativer Ladeprüfung einen
Beleg für genau diesen Gegner mit 769 HP. Ein privater vorgeschalteter
Filter begrenzte den echten Adapter zusätzlich auf diese eine GUID, diese
Host-Sitzung, Generation und Beobachtungssequenz sowie denselben geschützten
Prozess und Load. Es gab keinen Steam-Peer, Host-Schuss oder Netzwerk-Roundtrip.
Der normale Gast-Schutz und die nativen Adapterprüfungen wurden nicht gelockert.

## Ergebnis

| Prüfung | Beobachtet |
|---|---|
| Echte Adapteranwendung | Genau einmal 770 → 769 HP an der vorhandenen Gegnerkomponente |
| Unabhängiges natives Rücklesen | 769 HP; gleiche GUID, aktiv und lebend, `is_dead=false` |
| Drei frische Rücklesebestätigungen | Belegsequenzen 3, 4 und 5; jeweils ein erhaltener Anwendungsbeleg |
| Erneute Bestätigung derselben Hostprobe | Zweimal `already_seen`, keine weitere Adapter-Schreibung |
| Ende der lokalen Hostquelle | `available=false`, `reason=peer_unavailable`; letzter Anwendungsbeleg mit Vorher-/Nachher-HP bleibt erhalten |
| Speicher-/Ladebeobachtung | Ein erlaubter Load, null verweigerte Loads, keine gezählte Lua-Speicheranforderung |
| Native Steam-Sperre | Alle zehn Writerzähler null in einer Beobachtung nach der HP-Anwendung |
| Dateivergleich nach Prozessende | Alle zwölf Dateien bytegleich; keine neue Save-Datei |
| Rückbau | Eigene Instanz geschlossen, temporäre Skripte entfernt, Token/Konfiguration zurückgestellt, installierte Runtime unverändert |

Die [bereinigten Ergebniswerte](../../validation/native-campaign-hp-2026-11-17.json)
enthalten keine Steam-Kennung, Speicherdatei, Save-GUID oder Prozessadresse.
Der Rohbericht bleibt lokal; sein SHA-256 ist zum Abgleich im Ergebnis
enthalten. Zwei frühere Vorbereitungsläufe endeten vor der HP-Anwendung
wegen einer falschen Berichtsfeldzuordnung bzw. eines zu kurzen Wegziels.
Sie sind keine positiven Abnahmen; auch dabei blieben zwölf Dateien
unverändert und es gab keine HP-Schreibung.

## Bedeutung und nächste Abnahme

Bestätigt ist die begrenzte Anwendung eines positiven autoritativen HP-Werts
an einem realen, frisch zugeordneten Kampagnengegner, einschließlich
Wiederholungsschutz und erhaltenem Nachweis nach Quellenverlust. Der private
Test fügt diese Fähigkeit nicht automatisch zum installierten Teststarter
hinzu. Der Entwurf baut auf #103 auf; die Lade-/Timeline-Entwürfe #104/#105
wurden nicht in diese Fassung integriert und keine PR wurde zusammengeführt.

Offen bleiben insbesondere die echte Host-/Gastübertragung mit zwei Konten,
normale Treffercallbacks, Trefferreaktionen, Gliedmaßen, Tod, Kills,
Beute-/Skriptnebenwirkungen, weitere Gegnertypen/Bossphasen sowie die
Wiederherstellung der gesamten Welt nach Verbindungsabbruch. Ein direkter
positiver HP-Setter ist kein Nachweis eines natürlichen Treffers oder
eines vollständigen Todesablaufs. Als Nächstes müssen diese Engine-Pfade
getrennt beobachtet und anschließend auf beiden echten Instanzen verglichen
werden.
