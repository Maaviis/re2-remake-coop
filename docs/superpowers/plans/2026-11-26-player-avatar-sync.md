# Spielfigur-Synchronisation für Host und Gast

**Ziel**  
Zwei Spieler steuern ihre Figuren unabhängig in derselben Kampagne. Der Host spielt die Figur der gewählten Geschichte, der Gast die jeweils andere. Beide sehen Modell, Bewegung und die Aktionen des Partners. Die erste Abnahme im geschützten RE2-Profil verlangt ein sichtbares Partnermodell und nachweisbare Wechsel zwischen Stehen, Gehen und Laufen mit simuliertem Gast.

**Architektur**  
Der bestehende Pfad vom lokalen Pose-Beobachter über die Steam-Bridge zum Avatar-Renderer bleibt die Grundlage. Die bestätigte Sitzungsrolle und das gemeinsame Szenario bestimmen die Figur. Für den Solotest speist eine eigene zeitgesteuerte Quelle Position, Drehung und verifizierte Clips in denselben Renderer. Installierte Modelle und Animationen werden über die vorhandenen REFramework-Schnittstellen geladen.

## Reihenfolge

- [x] Die Rollenübergabe vom verifizierten Kampagnenkontext in `re2_coop_guest_pose.lua` zum vorhandenen `campaign_avatar.lua` testen. Für Leon und Claire jeweils Host- und Gastansicht sowie fehlende Rollenbindung prüfen. Modell und Material gehören zur Partnerrolle. Der bestehende Schutzbeleg ist Voraussetzung.
- [x] Den Referenzlauf mit der vorhandenen F5-Vorschau auswerten. In einem geschützten RE2-Lauf mit `f4a4bfe` meldete der Renderer das Modell als sichtbar. Die native Clip-Prüfung bestätigte den Standclip `pl00_0160_KFF_Gazing_Idle_F_Loop` mit 88 beobachteten Framewechseln. Die Vorschau bezog den Clip in diesem Lauf von Leon.
- [ ] Einen unabhängigen simulierten Gast an den gemeinsamen Renderer anbinden. Der Gast bleibt kurz stehen, geht, läuft und dreht, während der Host stehen bleibt. Die Abnahme benötigt native Transform- und Animations-Rücklesung sowie einen sichtbaren Modellnachweis. Initial sollen sowohl Leon- als auch Claire-Kampagne auf TDB 70 geprüft werden.
- [ ] Gastfigur und unabhängige Steuerung im gemeinsamen Szenario nativ anbinden. Die Kampagnen-ID der Story und die lokale Figuren-ID getrennt halten. Bewusste Eingaben auf der einen Seite müssen beim Gegenüber als sichtbare Bewegung mit dem passenden Clip ankommen. Szenenwechsel und Wiederanknüpfen dürfen keine alte Figur oder Pose zurückbringen.
- [ ] Die bereits übertragenen Aktionen wie Zielen und Schießen am sichtbaren Partnermodell prüfen und die verbleibenden Aktionen anhand nativer Beobachtungen anschließen. Bei fehlenden Clips, wechselnder Ausrüstung oder Modellverlust die Figur kontrolliert wiederherstellen. Synchronisation von Schaden, Inventar und Weltzustand braucht ihre bestehenden Zuständigkeiten und eigene Abnahmetests.
- [ ] Windows-ZIP aus dem getesteten Commit erzeugen. E2 aus Unit-, Paket- und Transporttests, E3 aus isoliertem RE2 und E4 aus zwei echten RE2-Instanzen mit getrennten Steam-Konten gemeinsam mit dem Dev-Lead dokumentieren.

## Koordination

Basis ist PR #156 auf `f4a4bfe`. PR #157 übernimmt Checkpoints und Fortsetzen. Arbeiten an gemeinsamer Kampagnenfreigabe, Wiederbeitritt mit gespeichertem Fortschritt oder Inventar werden vor einer Schnittstellenänderung mit Sasha abgestimmt. Die erste Änderung betrifft den Pose-Empfänger und den vorhandenen Avatar-Renderer.
