# Anforderungsaudit für RE2 Remake Koop

## Wiederholtes Speichern und Abbruch (26. November 2026)

Build `68c9535` bestätigt E3 mit der produktiven Host-Bridge und dem
identifizierten nativen Plugin. Ein erster nativer Checkpoint wurde
archiviert. Nach Annahme der zweiten Speicheranforderung meldete RE2
`busy=true`. Eine nur im privaten Testtreiber vorhandene, höchstens drei
Sekunden lange Unterbrechung des nächsten Updates ermöglichte das Beenden
des eigenen Prozesses. Die erste Generation und vier ältere bestätigte
Generationen blieben unverändert verifizierbar. Die zweite Anforderung
veröffentlichte keine Generation. Der Versuch belegt keinen Abbruch
während eines physischen Dateischreibzugriffs. Gast und gemeinsame
Freigabe waren simuliert. Die zwölf Originaldateien einschließlich Cache
wurden rückgeprüft; das ACL-Journal war nach geprüfter Rücksicherung entfernt.
[Abbruchmessung](validation/native-checkpoint-interruption-2026-11-26.json)

Der vorherige native Schutz entzog beim erneut identischen Slotindex die
Kampagnenkennung. Der Zielinhalt entsprach den übergebenen 240 Bytes,
während die reservierte temporäre Datei leer blieb. Die Korrektur erfasst
vor dem originalen Steam-Aufruf die vorhandene Dateiidentität und den
identischen Inhalt. Nach dessen Abschluss verlangt sie dieselbe private
Zieldatei mit derselben SHA-256 und eine unbenutzte eigene Reservierung.
Abweichende Inhalte und ersetzte Identitäten bleiben abgewiesen.
Die Archivierung akzeptiert einen unveränderten Slotindex zu einem
nachweislich erneuerten Autosave. Eine noch vorhandene `.stmp` bleibt
innerhalb der bestehenden Frist ausstehend; danach scheitert der Versuch.
[Ausgangsbefund](validation/native-identical-index-write-2026-11-26.json)

E2: 398 Python-Tests, 33 Lua-Suiten, drei native Speicherschutztests und
neun Tests mit der verpackten Python-Laufzeit bestanden. Das Steam-ZIP
enthält 103 Dateien, SHA-256
`0dc36fb9a0b64b4b9c8b963815d693ce2f77a23b1501ac1ee1b2eacb585fb540`.

Die Dateianzahl braucht eine begrenzte Wiederverwendung des Arbeitsordners.
Die lokale App-Konfiguration nennt 30 Dateien. Nach zuvor 30 Einträgen
zählte die spätere Steam-Abfrage 31, darunter eine leere, nicht persistierte
Reservierung eines älteren Abbruchversuchs. Freie Bytequote war vorhanden.
Ein früherer Originalaufruf für einen neuen Ordner lieferte Handle 0;
die genaue Steam-Abrechnungsregel ist nicht belegt. Der erfolgreiche
Kontrolllauf nutzte einen zusätzlich gesicherten vorhandenen Testordner.
Es wurden keine Steam-Dateien gelöscht oder vergessen.
[Kapazitätsmessung](validation/native-checkpoint-storage-capacity-2026-11-26.json)

Fortsetzen im laufenden Koop-Mount und die Abnahme mit zwei Konten bleiben
offen. #155 und #156 sind inzwischen in main. #157 bleibt ein eigener
Entwurf; der Vergleich mit main `b9d5938` zeigt einen Konflikt in STATUS.md.
Sasha prüft die Speicheränderung und stimmt den gemeinsamen Ladeübergang ab.

## Speichern und Fortsetzen aus dem Koop-Archiv (25. November 2026)

Der eigene Zweig aus [#157](https://github.com/Maaviis/re2-remake-coop/pull/157)
setzt auf #156 auf. Der Host kann nach bestätigter gemeinsamer Freigabe
einen nativen Autosave anfordern. Die Bridge archiviert die drei Dateien
als eigene Generation und findet nach dem Neustart die vollständigen,
unbeschädigten Generationen des aktiven Kontos.

E3 für Paketstand `4adde3f` belegt den nativen Speicheraufruf im
geschützten Koop-Ordner und das Laden derselben Dateien in einer frischen
RE2-Instanz. Die Gastfreigabe beim Speichern war simuliert. Der Rückladetest
verwendete eine geschützte Arbeitskopie mit ausschließlich den drei
Checkpoint-Dateien. Leon A, Standard, Karte 174 und ein vorhandener
Spieler wurden bestätigt. Der Guard meldete einen erlaubten und keinen
verweigerten Ladeaufruf. Originaldateien, ursprüngliche Ordneridentität,
Steam-Dateicache und Zugriffsrechte wurden rückgeprüft.
Der [Messbericht](validation/native-host-checkpoint-roundtrip-2026-11-25.json)
benennt Umfang und offene Abnahmen.

Die automatisierten Prüfungen erreichen E2. 393 Python-Tests, 33
Lua-Suiten und sieben native Windows-Tests bestanden lokal.
Der GitHub-Lauf für `4adde3f` ist grün. Das lokale Steam-ZIP umfasst
103 Dateien mit SHA-256
`49ea767754faf0ce2909f25e49036f1da9257cccb2cc7413ab2a5b1c1648c0de`.

Der gespeicherte Dateibestand liefert nach dem Neustart einen älteren
Slot-Zeitstempel als der SaveDataManager unmittelbar nach dem Speichern.
Der Ladeversuch mit dem frischen Speicherzeitstempel wurde vor dem
nativen Aufruf abgewiesen. Mit der aktuell aus genau dieser Arbeitskopie
gelesenen nativen Referenz gelang der Weltübergang unter denselben
Schutzprüfungen. Zwei weitere Vergleiche zeigen, dass die Werte exakt
mit den lokalen Kalenderwerten von Steams `GetFileTimestamp` für die
jeweiligen Dateipfade übereinstimmen. Die Ladefreigabe muss die native
Referenz nach dem Einsetzen der Arbeitskopie neu erfassen.
Der [Zeitstempelvergleich](validation/native-checkpoint-file-timestamps-2026-11-25.json)
dokumentiert die Messwerte.

Der vorhandene Ladevergleich verwendete für Autosave-Slot 0 fälschlich
`data000Slot.bin`. Ab `2824427` prüft er die von RE2 erzeugte Datei
`data000.bin`. Im erneuten E3-Rückladetest lieferte dieser normale
Dateivergleich exakt die archivierte SHA-256. Die native Instanz
erreichte erneut die Spielwelt. Der
[Prüfbeleg](validation/native-autosave-preflight-2026-11-25.json) trennt
die Version des Python-Dateivergleichs von den verwendeten nativen Modulen.

Die gemeinsame Fortsetzen-Auswahl, der Wiedereinstieg über einen
normalen Steam-Start und das Gastprofil ohne passenden alten Slot
stehen aus. Der PR beschreibt für Sasha die dafür nötige Erweiterung
der gemeinsamen Start- und Ladefreigabe. Das persönliche Gastinventar
folgt nach der Abnahme dieses Ablaufs.

## Aktueller gemeinsamer Kampagnenzweig

Dieser Zweig setzt den Gegner- und Türabgleich auf den aktualisierten
Kampagnenzweig aus #142. Er enthält dessen sichtbaren Kampagnenstart,
Paketprüfung und Erkennung umgeleiteter Steam-Spielstandpfade.
Der Steam-ZIP-Test verlangt jetzt auch die Lua- und Python-Dateien für
den Vergleich nach unterbrochener Kampagne. Die Anleitung dafür steht
in [SHARED_LOAD.md](SHARED_LOAD.md#vergleich-nach-unterbrochener-kampagne).
Die Einzelmessungen unten stammen aus den jeweils dokumentierten
Diagnoseläufen. Die gemeinsame Abnahme mit zwei Steam-Konten steht aus.

## Türen nach unterbrochener Kampagne

Der Terminalvergleich meldet Abweichungen bei Türen der geladenen Szene
als eigene Kategorie. Er prüft den aktuellen Öffnungs- und Schlosszustand,
die Öffnungsseite bei offenen Türen und den gespeicherten Öffnungsstatus.
Für die lokale Kennung verwendet er Kartenkennung, Ordner-Hash und
Objektname. Beide Seiten lesen unter derselben jeweils bestätigten
nativen Unterbrechung. Der Vergleich sendet einen SHA-256-Wert und lässt
die native Pause aktiv. Türänderungen während des Spiels, die Anwendung
beim Gast und die Abnahme mit zwei echten Steam-Instanzen stehen aus.

Zwei geschützte RE2-Starts mit Slot 4 vom 11.11.2026 lieferten nach
simulierter Unterbrechung jeweils drei stabile Messungen. Alle 68 Türen
hatten dieselben eindeutigen Kennungen und denselben Zustand. Zwei
waren schlüsselverriegelt. Bei 28 war eine frühere Öffnung gespeichert.
Alle zwölf geprüften Save- und Cache-Dateien blieben pro Lauf bytegleich.
[Messwerte](validation/native-interrupted-door-state-2026-11-23.json)

## Gegnerzustand nach unterbrochener Kampagne

Der Terminalvergleich prüft zusätzlich den aktuellen Gegnerzustand und
die gespeicherten Gegnerdaten samt gesamtem Killzähler. Der native
Leser bestätigt dieselbe Unterbrechung vor und nach der Beobachtung.
Veraltete Beobachtungen oder eine andere Ladebindung brechen die
Prüfung ab. Die Tests prüfen getrennte Abweichungen bei Live-HP und
beim gespeicherten Zustand. Die Anwendung des Hostzustands und die
Abnahme mit zwei echten Steam-Instanzen stehen aus.

Ein geschützter Einzeltest auf Slot 4 vom 11.11.2026 erreichte nach
simuliertem Verbindungsverlust eine native Pause mit fünf Controllern
in der Aktivliste und 87 gespeicherten Gegnerdatensätzen. Drei frische
Messungen bestätigten beim beobachteten Zombie 770 Live- und
gespeicherte HP. Die Liste enthielt den Controller weiter, während
das Aktiv-Flag aus war. Alle zwölf geprüften Dateien blieben bytegleich.
[Messwerte](validation/native-interrupted-enemy-state-2026-11-22.json)

## Nativer Todesübergang am Standby-Zombie

In einer geschützten RE2-Instanz mit Slot 4 vom 11.11.2026 kehrten
der native HP-Aufruf und der getrennte `applyDead()`-Aufruf für
denselben Zombie zurück. Vier spätere Proben zeigten Live-HP 0,
gespeicherte HP 770 und Killzähler 19. Es gab keinen
`onDead`-Callback. Zwölf geprüfte Dateien blieben bytegleich.
Die Gastanwendung braucht einen Referenzlauf mit laufender KI und
regulärem tödlichem Treffer.
[Messwerte](validation/native-death-transition-2026-11-22.json)

## Native Zombie-Todesbelege im Kampfkanal

Der Host kann einen ausgeführten nativen Todescallback mit einem
späteren Zustandsbericht desselben Zombies verknüpfen. Er liefert
dadurch eine eigene Ereigniskennung. Der Gast kann den Beleg im
Kampfbericht verfolgen. Tests decken fehlende, verspätete oder fremde
Callbacks sowie die Auflösung über einen eliminierten
Speicherkontext nach Entfernung des Controllers ab. Ein echter
zwei-PC-Kampftest und die native Todesanwendung fehlen.
Die Registrierung des Beobachters gelang im geladenen RE2 mit Slot 4 vom
11.11.2026 und simulierter Host-Bindung. Der Lauf beobachtete null
Todescallbacks und null Lesefehler. Alle zwölf Dateien blieben bytegleich.
[Messwerte](validation/native-campaign-death-registration-2026-11-22.json)

## Kampagnenfreigabe und Gegnerabgleich im selben Build

Der aktualisierte Stand aus #136 enthält positiven Gegner-HP-Abgleich
und bestätigte positive Gasttreffer im selben Gebiet. Der gemeinsame
Entwicklungsstand kombiniert dies mit der beidseitigen Startbestätigung
und dem Vergleich nach einer Unterbrechung. Ein eigener Steam-Kanal
trägt Gegnerdaten und Treffer. Er startet erst nach der nativen Freigabe
beider Instanzen. Fehlen bestätigte Kampfübertragungen zehn Sekunden,
endet die laufende Freigabebestätigung und der native Pausenpfad greift.
Die Tests simulieren beide Verbindungen, eine fehlende Kanalbindung und
ausbleibende Bestätigungen. Die Zwei-PC-Abnahme und die Synchronisierung
von Gegner-Tod und vollständigem Weltzustand stehen aus.

## Kombinierter Steam-Kampagnenkandidat (23. November 2026)

Auf Windows kann Steam für ein umgeleitetes `userdata` den physischen
Spielstandpfad melden. Der Neustarthelfer akzeptiert diesen Pfad nur, wenn
er zum registrierten Steam-Ordner gehört. Ein Windows-Test mit echter
Junction bestätigte die Pfadauflösung, die Ablehnung eines fremden Ordners
und den bytegleichen Rückbau der synthetischen Originaldatei. Der
geschützte Neustart mit diesem Layout in RE2 bleibt offen. Siehe #148.

PR #142 enthält jetzt den aktuellen #136-Zweig samt Lobby- und Paketkorrekturen.
Der Stand `3fe6a2b` besteht lokal 354 Python-Tests und 27 Lua-Suiten. Beide
Windows-x64-DLLs bauen; je drei Lobby- und Save-Barrier-Ctests sowie die
Windows-Speicherschutz-/Recovery-Fixtures bestehen. CI-Lauf #270 ist mit beiden
Jobs grün: [Ergebnisse und Testartefakte](https://github.com/Maaviis/re2-remake-coop/actions/runs/45092504666).

Der lokal gebaute Steam-Mod-ZIP enthält 90 Dateien, null `.md`-Dateien und
Bridge, Lobby, Startknopf sowie Speicherschutz. Der ZIP-Hash ist
`1b38a7814be2dfd4986375c0d41fbad8c1f843c23f08e2867562dce784010462`; die
beiliegende SHA-256-Datei stimmt überein. Die neue Regression deckt den
Steam-Paketinhalt und den Ausschluss von Markdown ab.

Das ist Build-, Paket- und Fixture-Nachweis. Dieser Kandidat wurde noch nicht
im echten RE2 gestartet. Zwei Steam-Konten, gemeinsamer Kampagnenstart,
beidseitige Figurendarstellung, Bewegung und ein synchronisierter Treffer
bleiben offen.

## Vergleich nach unterbrochener Kampagne

Der Terminalvergleich meldet Host und Gast nach erneuter Steam-Verbindung
getrennte Ergebnisse für das aktuelle Gebiet, den Ladekopf und die
Inventarkernwerte. Beide brauchen den ursprünglichen Ladeversuch, den
aktuellen Speicherschutz und eine bestätigte native Pause. Die Tests
simulieren zwei Instanzen mit abweichendem Gebiet und Inventar.
Im echten RE2 lieferte die erneut bestätigte Pause zu Slot 4 vom
11.11.2026 das aktuelle Gebiet und drei jeweils neue Inventarproben mit
Ladekopf. Alle zwölf geprüften Dateien blieben bytegleich.
[Messwerte](validation/native-interrupted-checkpoint-2026-11-22.json)
Der native Vergleich auf zwei Rechnern und die Wiederherstellung der
gesamten Welt stehen aus.

## Native Freigabebestätigung auf beiden Seiten

Nach dem Startbefehl bestätigen beide Bridges die tatsächlich aufgehobene
native Pause desselben Versuchs. Der Controller aktiviert den Kampagnenbeleg
für Posen erst bei frischer Bestätigung des Peers. Bei ausbleibender oder
abgelaufener Bestätigung greift die erneute Pause auch bei weiterhin aktiver
Steam-Verbindung. Python- und Lua-Tests prüfen fehlende, fremde und
wiederholte Bestätigungen sowie den Ablauf nach erfolgreicher Freigabe.
Im echten RE2 wurde Slot 4 vom 11.11.2026 geschützt geladen. Bei gesund
gemeldeter simulierter Verbindung ohne zweiten Freigabebeleg griff die
native Pause nach zehn Sekunden. Drei Messungen der Spiel-, Rekord- und
Szenenzeit blieben gleich. Alle zwölf geprüften Dateien blieben bytegleich.
[Messwerte](validation/native-campaign-peer-release-timeout-2026-11-22.json)
Die Abnahme des Austauschs zwischen zwei RE2-Instanzen und der gemeinsame
Weltzustand nach einem Abbruch stehen aus.

## Pausenbehandlung nach der Kampagnenfreigabe

Der Lua-Controller entzieht den Kampagnenbeleg bei einem abgelaufenen Bericht
oder einer gewechselten Steam-Verbindung. Für denselben Spieler, dieselbe
Szene und denselben Spielfluss versucht er erneut die native Menüpause.
Die Lua-Tests decken die Rückkehr aus dem Menü, einen Wechsel während der
Freigabe, fremde Pausen und die Wiederholung alter Befehle ab.
Nach Prüfung des vorhandenen Schutzcodes gegen das Archiv zu #132
bestätigt ein Test in einer echten RE2-Instanz die erneute Pause nach
simuliertem Verbindungsverlust. Drei Messungen der Spiel-, Rekord- und
Szenenzeit blieben gleich. Zwölf Save- und Cache-Dateien blieben bytegleich.
Ein echter Steam-Abbruch und der Weltabgleich beim Wiederbeitritt bleiben
offen. [Messwerte](validation/native-campaign-rehold-2026-11-22.json)

## Vorbereiteter Lobby-Start im Paket (20. November 2026)

Der geschützte Paketstarter gibt auf beiden Rollen die aktive Save-Quelle
an den vorhandenen Lobbyvergleich weiter. `Spielstand-laden.cmd` prüft die
passende aktive Bridge und verlangt bei aktiviertem Vergleich den gemeinsamen
Versuch und den lokalen Pausenbeleg. #124 korrigiert die Zuordnung des
Windows-Schutzbelegs nach der Pfadauflösung. 288 Python-Tests, 20 Lua-Suiten,
drei native CTests und die Windows-Schutzprobe bestehen.

Mit `b058489` wurde in einer echten RE2-Instanz die private Host-Lobby und
die Abweisung eines vorbereiteten Ladebefehls ohne Gast bestätigt. Die 23
kopierten Save-Dateien blieben unverändert. Der Rückbau und die ursprüngliche
Cloud-Einstellung wurden geprüft. Der positive Zwei-Konten-Ladeablauf
steht aus. [Paketprüfung](TEST_PACKAGE.md#vorbereiteter-start-aus-dem-paket)

## Gemeinsamer CI-Download (20. November 2026)

PR #123 erstellt nach den Pflichtprüfungen ein Manifest-ZIP mit SHA-256-Datei
und verlinkt es in der Jobzusammenfassung. Acht Exporttests prüfen unter anderem
den Ausschluss lokaler Dateien, Verknüpfungen, bestehende Ausgabe und konstante
ZIP-Metadaten. Insgesamt bestanden 280 Python-Tests und 20 Lua-Suiten; beide
CI-Jobs einschließlich Paketbau und eingebetteter Importprüfung sind grün.

Der tatsächlich heruntergeladene CI-Stand `9e3f349` wurde zusätzlich lokal in
RE2 über Installer, Hoststarter, private Steam-Lobby, Load und Uninstaller
geprüft. Fünf unterschiedliche native Sequenzen, 23 bytegleiche Spielstand-
dateien und der vollständige Rückbau sind bestätigt. Quelle, Download,
Prüfsumme und Grenzen stehen in
[TEST_PACKAGE.md](TEST_PACKAGE.md#nativ-geprüfter-ci-download-vom-20-november-2026).
Die Zwei-Konten-Abnahme und eine spielbare Koop-Kampagne bleiben offen.

## Vollständiger Paketablauf auf einem Rechner (20. November 2026)

Der Paketstand `88ceb93` erlaubt eine explizite lokale Datumsfreigabe bei der
Installation. Lobbyfilter und Ladebefehl verwenden dieselbe Einstellung;
alte Zustände behalten 2026-11-11. Die Wiederinstallation erhält ein zuvor
nachweislich zurückgebautes Paket im neuen Backup. Ein abgebrochener Zustand
mit `active=false` gilt dabei nicht als abgeschlossener Rückbau.

Installer, Hoststarter, Load, Status, Stop und Uninstaller liefen mit dem
enthaltenen Python 3.13.17 tatsächlich in RE2. Eine private Steam-Lobby wurde
im Terminal erstellt, der lokale alte Slot vom 08.04.2026 geladen und fünf
unterschiedliche native Sequenzen bestätigt. Die isolierte Kopie lag unter
allen vorgesehenen Testschutzschichten. Alle 23 Speicherdateien und die
24/31/5 zurückgestellten Steam-/Framework-/Konfigurationsdateien sind geprüft.
[TEST_PACKAGE.md](TEST_PACKAGE.md#paketprüfung-vom-20-november-2026) dokumentiert
Umfang und die noch fehlende Zwei-Konten-Abnahme. 272 Python-Tests und
20 Lua-Suiten bestehen; native Builds und drei CTests ebenfalls.

## Quellenintegration von Speicherschutz und Ladepause (20. November 2026)

#103 und #117 sind in einem gemeinsamen Entwicklungszweig integriert.
Schema-1- und Schema-2-Ladebefehle verlangen die native Steam-Sperre und den
Starterbeleg mit vererbten Dateisperren. Der Lobbyprozess muss dem geschützten
Spiel entsprechen; ein Startwechsel während des Dateivergleichs bricht ab.
Checkpoint und Lua-Pausenbeleg prüfen den Schutz ebenfalls. Bei Schutzverlust
bleibt eine gehaltene Pause bestehen, ohne einen positiven Abgleich zu melden.
Die zusätzliche Verzeichnis-, ACL- und Cloud-Prüfung bleibt für vorbereitete
Loads Pflicht. Die Windows-Fixture bestätigt vererbte Dateihandles und
Kindprozessstart auch unter aktivem ACL-Schutz sowie den anschließenden
Rückbau. Das ist eine Prüfung an künstlichen Dateien. Zusätzlich bestand
der unten beschriebene lokale RE2-Test. Die lokale Paketprüfung steht oben;
die Zwei-Konten-Abnahme des kombinierten Standes bleibt offen.

Lokal bestanden 259 Python-Tests, 20 Lua-Suiten, beide nativen Windows-x64-
Builds mit insgesamt drei CTests und die Windows-ACL-/Wiederherstellungsprobe
einschließlich des kombinierten Handle-Tests. Die Regressionen zu #118
scheiterten vor den Bindungsprüfungen und bestehen danach. #119 erfasst die
unter Python 3.11 korrigierte Reparse-Prüfung des Paketinstallers; eine echte
temporäre Windows-Junction wird weiterhin abgewiesen.

Der native Einzelinstanz-Lauf auf `ebf08e4` bestätigte das Laden des lokalen
alten Slots 4 vom 8. April 2026 unter vererbten Dateisperren, nativer
Steam-Sperre, ACL-Schutz und deaktivierter Cloud. Fünf frische native Proben,
ein vom Steam-Guard gezählter und abgewiesener Plattform-Schreibaufruf sowie
23 auch nach Spielende bytegleiche Speicherdateien sind bestätigt. Der echte
Pausencontroller hielt eine synthetische lokale Anforderung ohne Peer in
drei frischen Proben. Nach Ablauf des Starterbelegs wurde der Schutzstatus
ungültig, während die Pause erhalten blieb. 24 originale Steam-Dateien,
31 Framework-Dateien und fünf Konfigurations-/Logdateien wurden bytegleich
zurückgestellt; die ursprüngliche Cloud-Einstellung ist wieder aktiv.
[SAVE_PROTECTION.md](SAVE_PROTECTION.md#kombinierter-nativer-einzelinstanz-test-am-20-november-2026)
grenzt diesen Lauf vom gemeinsamen Load, Weltstillstand und echten
Autosave-/Checkpoint-Ereignis ab.

## Lesende Timeline-Messung (17. November 2026)

Maaviis/Codex ergänzt auf #104 einen getrennten, optionalen nativen Leser
für Timeline-Aktivität. Kameraereignisse, Inhaltskennungen, echte
Timeline-Frames und Audio-Zähler bleiben getrennt; widersprüchliche
Doppelabfragen werden verworfen. Der native Einzelinstanz-Test bestätigt
den fertigen Leser nur ohne aktive Zwischensequenz. 233 Python-Tests und
20 Lua-Suiten bestehen. [TIMELINE_ACTIVITY.md](TIMELINE_ACTIVITY.md)
dokumentiert Umfang und offene Laufzeitpfade.

Der Leser erreicht inzwischen über die `TimelinePerformance` jedes aktiven
Inhalts auch freie Ereignisse ohne Kameraquelle. Native Getter-Signaturen
sind geprüft; zugehörige IDs und Framewechsel sind mit Fixtures abgesichert.
Unterformat 2 trennt fehlende Ausführung, Ereignisinformation und Timeline.
Eine tatsächliche freie Wiedergabe bleibt gesondert nativ abzunehmen.

Nächster Schritt: tatsächlich laufende Kamera-/freie Timeline und Filme
mit stabilen Kennungen beobachten, danach Start, Pause, Skip und Ende
getrennt abnehmen. Der Freund kann später an einem Zwei-PC-Test teilnehmen;
bis zu seinem Testtermin bleibt die gemeinsame Abnahme ausstehend. Das
installierte Verbindungspaket 4494ef2 bleibt unverändert. Vollständige
Weltanwendung und gemeinsame Spielfreigabe sind weiterhin offen.

## Pausennachweis für vorbereitetes Laden (17. November 2026)

Ein eigener Controller fordert nach zugelassenem Load die vorhandene
native Pause an. Der Checkpoint-Vergleich verlangt ihren frischen Beleg
vor/nach dem Lesen sowie während der zweiten Peer-Bestätigung. Fehlende,
fremde, beendete oder veraltete Pausen ergeben keinen positiven Vergleich.
Die installierte Verbindungstestfassung wird dadurch nicht erweitert.

Der lokale native Negativtest verwendete nur den freigegebenen alten Slot 4,
vererbte Dateisperren und die native Steam-Sperre. Mit ausdrücklich
synthetischem Versuch ohne Peer wurde `held` erreicht; tatsächliche
Spielzeit, Rekordzeit und Szenenzeit blieben in drei frischen Proben gleich.
Die Komponente gab erwartungsgemäß keinen gemeinsamen Checkpoint frei.
Ein Load, null verweigerte Loads, keine gezählte Speicheranforderung und
zwölf unveränderte Dateien sind bestätigt. Vollständiger Weltstillstand,
beide echten Instanzen und automatisches gemeinsames Fortsetzen bleiben
offen. [PREPARED_LOAD_PAUSE.md](PREPARED_LOAD_PAUSE.md) grenzt den Befund ab.

## KI-Flags separat erfasst (18. November 2026)

Maaviis/Codex ergänzt den Gegnerleser um eine ausdrücklich optionale
Aktivitätsdiagnose. Der Standardbericht und die bestehende Steam-Anbindung
bleiben unverändert. Die Zusatzprobe vergleicht native Think-Freigabe,
Denkobjekt, LastStay-Karten und Objektidentitäten über zwei Erfassungen;
keine KI wird eingeschaltet und keine Todesanwendung ergänzt.

Der geschützte native Vergleich mit altem Slot 4 ergibt neun frische
Sequenzen: fünf aktive Controller, alle mit deaktivierter Denklogik. Der
lebende Zombie behält 770 HP. Spieler-LastStay liegt bei Karte112/Bereich5,
die Controller melden119 beziehungsweise239. Diese Werte belegen keine
Streaming-Abdeckung beider Spieler. Alle zwölf Dateien bleiben bytegleich;
die eigene Instanz ist geschlossen und temporäre Skripte sind entfernt.
[ENEMY_ACTIVITY.md](ENEMY_ACTIVITY.md) grenzt Befund und Folgearbeit ab.
Alle 20 Lua-Suiten bestehen. Das installierte Paket bleibt4494ef2.

Nächster Kampfschritt bleibt ein tatsächlich simulierter Gegner mit
natürlichem Treffer, positivem Callback und vollständigen Nebenwirkungen;
danach Host-Aktivität für beide Spielerbereiche und Abnahme mit zwei PCs.
Der Freund ist erst später zum Test verfügbar.

## Todespfad: KI-Aktivität getrennt prüfen (18. November 2026)

Maaviis/Codex ergänzt einen getrennten passiven Beobachter für Em0000ThinkBase.onDead.
Metadatenvorbereitung registriert noch keinen Hook; erst bestätigte native
Szenenbereitschaft erlaubt den Start. Die konkrete Klasse Em0000Think löst
nativ dieselbe Methode auf. Die 20 Lua-Suiten bestehen mit dem neuen Beobachter.

Der geschützte reale Grenzfall nach einer nativen addDamage-Anforderung zeigt
60 unterschiedliche Proben über zehn Sekunden mit HP0/is_dead=true/is_live=false,
aber weiterhin deaktivierter KI, Killzähler19 und keinem aufgezeichneten
onDead-Callback. Alle zwölf Dateien blieben unverändert; die eigene Instanz
ist geschlossen. [DEATH_OBSERVER.md](DEATH_OBSERVER.md) hält Grenzen und die
bereinigten Messwerte fest. Dies ist keine positive Todes-/Koop-Abnahme.

Nächster Schritt: tatsächlich laufende Gegner-KI und ursprünglichen Trefferpfad
prüfen; Aktivität/Streaming für beide Spielerbereiche und den vollständigen
Todeszustand definieren. Der positive HP-Adapter und das installierte Paket
bleiben unverändert. Ein Null-HP-Setter allein wird nicht als Todesanwendung
integriert. Natürliche Treffer, positiver Callback, Nebenwirkungen, Rejoin und
zwei echte Steam-Konten bleiben offen. Der Freund kommt erst später zum Test.

## Echte positive HP-Anwendung (17. November 2026)

Maaviis/Codex bestätigt auf der geschützten Runtime 4494ef2 den unveränderten
HP-Adapter erstmals an einem echten Kampagnengegner: einmal 770 → 769 HP,
frisches natives Rücklesen, zweimalige Wiederholungsabwehr derselben
Hostprobe und erhaltener Beleg nach Quellenverlust. Die Hostquelle wurde
lokal erzeugt; kein zweites Steam-Konto war beteiligt. Alle zwölf Dateien
blieben unverändert, der eigene Prozess ist geschlossen und die temporären
Erweiterungen sind entfernt. [NATIVE_CAMPAIGN_HP.md](NATIVE_CAMPAIGN_HP.md) und die dort
verlinkten bereinigten Ergebniswerte grenzen den Nachweis ab.

Nächste Kampfabnahme: natürlicher Treffer, Todesablauf und Nebenwirkungen
an echten Kampagnengegnern, danach der beidseitige Test mit zwei PCs. Der
Freund ist später verfügbar; bis zu seinem Termin wird an den unabhängigen
Engine-Pfaden weitergearbeitet. Das installierte Verbindungspaket bleibt
unverändert. #104/#105 sind getrennte Lade-/Timeline-Entwürfe und nicht in
diese Schutzfassung integriert. Vollständige Koop-Synchronisation bleibt offen.

## Sicherheitsbefund und neuer Teststarter (17. November 2026)

Ein regulärer Checkpoint verkürzte den Autosave trotz 26 aktiv gemeldeter Lua-Hooks. Der alte Testaufbau wurde zurückgenommen; Originalsaves sind lokal wiederhergestellt und laut Steam-Uploadprotokoll wieder vollständig in der Cloud. Der neue native Steam-Guard plus vererbte Windows-Dateisperren bestanden einen lesenden Einzelinstanz-Load des erlaubten alten Slots: drei frische Spielerproben, ein erlaubter Load, null verweigerte Loads und unveränderte zwölf Dateien. Die Ladefreigabe verlangt nun aktuelle Schutzbelege derselben Instanz. Ein gezielt ausgelöster nativer Autosave-Schreibtest und zwei echte Steam-Konten wurden damit nicht geprüft. [SAVE_PROTECTION.md](SAVE_PROTECTION.md) enthält Befund, Wiederherstellung und Abnahmegrenzen.

Die installierte Paketfassung `4494ef2` bestätigte anschließend den Hostpfad mit privater Steam-Lobby, geladenem alten Slot und frischer Spielerpose sowie den separat gestarteten Gast im Warten ohne Einladung. Beide Schutzschichten waren aktiv. Nach jedem dieser Einzelinstanz-Läufe entsprachen alle zwölf Dateien der Sicherung. Der im ersten Paketlauf gefundene Windows-Konflikt beim Status-Ersetzen wurde mit begrenzter Wiederholung behoben und an künstlichen Dateien nachgestellt. [TEST_PACKAGE.md](TEST_PACKAGE.md) grenzt diese Paketprüfung von der weiterhin offenen Verbindung zweier Konten ab.

Stand: 15. November 2026. Der Integrationsstand führt die Entwicklungszweige #8 bis #61 zusammen. Die native Hauptmenü-Auswahl aus #57 und die Steam-Lobby-Erstellung aus #61 sind in [LOBBY_MENU.md](LOBBY_MENU.md) und [LOBBY_TEST.md](LOBBY_TEST.md) dokumentiert. [GAMEPLAY_PAUSE.md](GAMEPLAY_PAUSE.md) beschreibt den nativen Einzelinstanz-Nachweis aus #60. Für die Koop-Abnahme sind zwei echte RE2-Instanzen mit zwei Steam-Konten erforderlich.

## Aktueller gemeinsamer Prüfstand

Der passive [Treffercallback-Beobachter](DAMAGE_OBSERVER.md) ist ein eigener Entwurf auf #87. Die native Installation und ein ausschließlich per Terminal ausgelöster Ziel-/Schussversuch sind bestätigt (Munition vier auf drei, danach beide eigenen Aktionsbitbereiche null). Der Schuss erzeugte keinen Gegnertreffer; positive Callback-/Killzuordnung und beide echten Spielinstanzen bleiben ungeprüft. Es findet keine Übertragung oder Anwendung dieser Diagnosedaten statt.

Der Integrationsentwurf vom 16. November fasst die 15 PRs #70 bis #84
auf Basis von `main` bei `7679b2a` zusammen. Er enthält native
Lobby-Rückkehr und Sitzungswechsel, den Gegnerleser, Snapshot-Framing,
den parallelen Pose- und Gegnertransport sowie Fristprüfung und
Wiederholung des positiven HP-Abgleichs. Die Rücklesedatei hält
bestätigte Schreibvorgänge derselben Host-Probe je GUID fest, auch wenn
sie aus späteren Gastabrufen stammen. Die Spielabnahme mit zwei
Steam-Konten bleibt offen. Lokal bestanden 190 Python-Tests,
18 Lua-Einstiegssuiten, der Windows-x64-Plugin-Build und beide CTests.
Ein Einzelinstanz-Test in RE2 Build 11636119 bestätigte im Terminal
das Erstellen einer privaten Lobby, die parallele Erreichbarkeit
beider nativen Pipes ohne Steam-Peer und das Verlassen der Lobby.

Der optionale Ladebefehl `--prepared-lobby` bindet einen expliziten
lokalen Ladeaufruf an die frische Steam-Mitgliedschaft, den aktuellen
Vorprüfversuch und die lokale Save-Guard-Kennung. Python- und Lua-Tests
bestätigen den Dateivergleich, die erneute Gültigkeitsprüfung vor dem
Loader und die Abweisung wiederholter Versuche. Der gemeinsame native
Ladeablauf und die anschließende Weltfreigabe stehen aus.

Der Kampagnen-Prüfzweig verbindet #88/#89 und den Windows-Speicherschutz
aus #95 mit dem aktuellen Steam-Verbindungstest aus #99. Nach beiden
Ladebelegen vergleicht `--prepared-checkpoint` die Ladekopf-Digests in
zwei Transfers auf derselben Pipe-Epoche. Weicht eine Probe bei ihrer
abschließenden Prüfung ab, meldet keine Seite Erfolg.
Die Regressionen verwenden nachgebildete Steam-Pipes. Ein nativer
Einzelinstanz-Test auf `8a1a60b` bestätigte inzwischen `scene_loaded` und
fünf frische native Proben mit geschützter Steam-Spielstandkopie. Ein
kontrollierter nativer Plattform-Schreibaufruf wurde abgewiesen. Die 23
kopierten Speicherdateien blieben auch nach Spielende bytegleich. Die
ursprüngliche Installation und Cloud-Einstellung wurden wiederhergestellt.
[READONLY_LOAD.md](READONLY_LOAD.md#nativer-lade--und-schreibtest-am-17-november-2026)
beschreibt den Lauf. Auf `01dc553` wurden außerdem je eine native
Systemspeicher- und Autospeicheranforderung mitsamt ihrem Original-
Speicherarbeiter unter Windows-Schutz ausgeführt. Beide meldeten einen
Speicherfehler, und die 23 kopierten Speicherdateien blieben bytegleich.
Die Rückkehr aus dem Fehlerzustand, ein durch ein Weltereignis ausgelöster
Checkpoint und die Abnahme mit zwei Steam-Konten stehen aus.

[PR #62](https://github.com/Maaviis/re2-remake-coop/pull/62) ist in `main` zusammengeführt; #8–#61 sowie die Menü-/Einladungsnachträge #63/#67 sind enthalten. Alle 29 danach noch offenen Kopfstände wurden als Vorfahren von `main` geprüft und mit Verweis geschlossen. Der gemeinsame Folgeprüfstand einschließlich des nach ausdrücklicher Freigabe gemergten #68 besteht 146 Python-Tests, 15 Lua-Einstiegssuiten mit zusätzlichem Menücheck und den nativen Windows-Build mit zwei CTests. [AKTUELLER_STAND.md](AKTUELLER_STAND.md) bietet den verständlichen Überblick.

#60 bestätigt in einer Instanz gehaltene tatsächliche Spiel-/Rekord-/Szenenzeiten und die beobachtete Animation sowie vollständige Rückkehr über `PauseBehavior.toReturnGame()`. Die fertige Terminalprobe lieferte 28 beziehungsweise 14 frische gehaltene Samples. Andere Akteure, KI, Physik, Skripte und Cutscenes sind damit nicht nachgewiesen; die Bindung an Prozess-/Steam-/Link-Epochen und globale Ladeversuche bleibt offen. [GAMEPLAY_PAUSE.md](GAMEPLAY_PAUSE.md) enthält die Prüfgrenze.

Der lesende Menücheck aus #68 vergleicht vor der Einladung lokale Dateien, frische Eingabetelemetrie, Prozess, Bridge-Rolle und Lobbyzustand. Er bestätigt weder Einladung noch Nutzbarkeit einer zweiten Spielwelt.

Die neuere Menüabnahme aus #67 bestätigt laut LOBBY_MENU.md drei Öffnungen, Zurück/Esc und anschließende Originaloption in einer Instanz. Zwei echte Konten, Gastansicht sowie native Tastatur-/Controller-Aktivierung bleiben offen. Die folgenden Einzelbeitragsangaben bewahren den historischen Stand; insbesondere beziehen sich dortige Aussagen über noch offene PRs oder separate Menübranches auf die Zeit vor #62.

| Anforderung | Befund | Nachweis, der noch fehlt |
|---|---|---|
| Zwei Spieler in einer Kampagne | Eine veröffentlichte Fremdmod bewirbt eine Zwei-Spieler-Beta; unser Prototyp hat keinen gemeinsamen Kampagnenlauf mit zwei echten Instanzen nachgewiesen. | Beide Spieler starten denselben Kampagnenabschnitt und können unabhängig handeln. |
| Position und Aktionen | Ein Einzelinstanz-Test mit RE2 Build 11636119 und TDB 70 bestätigte die lokale Pose über Observer, v1-Loopback-Host und sichtbares statisches Testobjekt mit Transform-Rücklesen. Der bidirektionale Bridge-Test lief mit getrennten Datendateien als Prozess-Test. #22 beobachtete Animationsbank und Frames im Spiel; #23 spielte einen installierten Idle-Clip auf einem eigenen sichtbaren Testobjekt in einer Instanz ab. Der Observer aus #25 las im laufenden Claire-Spiel Bank, Clip, Frame und Pose; die Übertragung der nativen Claire-Probe bis zur Gastdatei wurde in einer Spielinstanz mit laufendem v1-Host und getrennten Observer-/Gastprozessen bestätigt. #26 ergänzte eine optionale Leon-Diagnosedarstellung. Ein nativer Einzelinstanz-Test mit synthetischer Gastpose bestätigte nach verzögerter Bankregistrierung den erwarteten Clip mit fortschreitenden Frames; echte Leon-Sendedaten fehlen. #31 führt eine experimentelle relative Phasenangleichung ein; CI ist grün, ein nativer Phasentest fehlt. #32 überträgt v1-Posen über bestätigte Steam-Peers in einem Prozesstest und hat die Pipe in einer Spielinstanz ohne bestätigten Peer geprüft; zwei echte Spielinstanzen fehlen. #33 ergänzt Terminalbefehle für den Motion-Test; der Client wurde lokal, die Lua-Verarbeitung bisher nur simuliert geprüft. #34 ersetzt im Steam-Posenpfad den Vergleich verschiedener Rechneruhren durch eine lokale Empfangsfrist; 67 Python-Tests und CI bestanden, ein Zwei-Rechner-Test mit Uhrversatz und Verzögerung fehlt. #37/#39/#40/#42 führen Steam-Posen, Leon-Motion, Ablauf und Sitzungsprüfung zusammen; 78 Python-Tests und die Lua-CI bestehen auf #42. Die Darstellung und Phasenangleichung sind in zwei echten Instanzen noch nicht geprüft. | Zwei echte RE2-Instanzen im selben Raum: beide Bewegungsrichtungen, Drehung, Sichtbarkeit und Abwesenheit. Danach kontrollierte Aktions-zu-Clip-Zuordnung und Wiedergabe auf einer animierten Gastfigur; Schießen und Interaktion in beiden Instanzen. |
| Gegner, Schaden und Tod | Der optionale Leser trennt Registry, gespeicherte Daten und aktive Controller. Ein nativer Einzelinstanz-Lauf bestätigte HP 770 → 769 → 0 und dieselbe GUID nach Aus-/Einstreamen. Das Speichermodell übernahm HP 0 erst beim Ausstreamen. Der Killzähler blieb gleich. Ein separater Versuch bestätigte den bestehenden HP-Adapter einmal am echten Zombie (770 → 769) bei lokaler synthetischer Hostquelle, einschließlich Wiederholungsschutz. Details in ENEMY_WITNESS.md und NATIVE_CAMPAIGN_HP.md. | Reguläre Treffer, Killverursacher, Nebenwirkungen, KI und Bossphasen messen und beidseitig anwenden. Live-Transport und Gastanwendung in zwei echten Instanzen abnehmen. |
| Rätsel und Türen | Im Modell repräsentiert; Engine-Anbindung fehlt. | Jede Zustandsänderung wirkt in beiden Instanzen und bleibt nach Laden erhalten. |
| Gegenstände und Inventar | Im Modell repräsentiert. #58 liest nach tatsächlichem Laden native Slot-Grundwerte, Mengen, Kennungen, Flags, Kapazität und Ausrüstung; fünf frische Samples bestätigten einen stabilen Kerndigest. #59 ergänzt als Draft getrennte Item-Payloads, innere/zusätzliche Daten und gerichtete Haupt-/Neben-Shortcuts mit 136 Python-Tests und elf Lua-Suiten. Nach vorherigen Abbrüchen unter protokolliertem Speichermangel bestätigte ein späterer frischer Lauf fünf gleiche Detail-Digests und die Lade-ID-Bindung des fertigen Readers in einer Instanz. Keine Zustandsanwendung. | Itembox, andere Inventare und Effektflags ergänzen. Aufnahme, Verbrauch, Transfer, native Anwendung und Wiederverbindung in beiden echten Instanzen prüfen. |
| Fortschritt und Skriptereignisse | Im Modell repräsentiert; sämtliche Kampagnenpfade unkartiert. | Vergleich der Fortschrittsflags und Ereignisreihenfolge über die gesamte Kampagne. |
| Alle Zwischensequenzen | Nur ein abstrakter Cutscene-Zustand im Modell. | Beide Instanzen zeigen Beginn, Zeitverlauf, Skip und Ende synchron für jede Szene. |
| Keine Abweichung, Wiederverbindung | v1-Handshake, Sequenz/Digest, Snapshot, Heartbeat und Diagnosegast-Rejoin sind mit Loopback-Prozesstests geprüft. #35 zeigt das Ausblenden und die automatische Übernahme einer neuen Host-Sitzung nach Bridge-Neustart in einer simulierten Steam-Verbindung. #38/#40 binden den Snapshot an eine Anfragekennung; ein Linux-CI-Fehler beim wiederholten Timeout ist in #40 behoben und mit einem Regressionstest sowie grüner CI geprüft. #41/#42 verwerfen Gast-Vorschläge aus einer alten Host-Sitzung. #43 setzt Lobby-Bereitschaft bei einem neuen Handshake und bei beobachtetem Verbindungswechsel zurück; der simulierte Bridge-Test bestätigt den Austausch und einen Host-Neustart. Kein Rejoin mit zwei laufenden RE2-Instanzen. | Abbruch während Kampf, Rätsel und Szene; erneuter Beitritt mit identischem Zustand. |
| Steam-Einladung | #28 bestätigte eine private Steam-Lobby und den Einladungsdialog in einer RE2-Instanz. #29 erfasste Einladungsanforderungen und wies eine synthetische, fehlende Lobby korrekt ab. #30 initialisierte Steam Networking Messages und wies `ping` ohne zweites Mitglied ab. #32 ergänzt den v1-Posenpfad über einen bestätigten Lobby-Peer, bislang mit Prozess- und Einzelinstanz-Tests. #34 prüft eine lokale Empfangsfrist bei künstlichem Uhrversatz im Python-Test. #42 kombiniert die geprüfte Gastpose mit dem Steam-Transport und der Host-Sitzungsprüfung; sein Prozess-Test verwendet einen simulierten Link. #44 leitet die Einladungsanforderung der Host-Bridge an die native Lobby-Pipe weiter. Im aufbauenden Zweig #45 öffnete ein terminalgesteuerter Klick auf den sichtbaren Lobbyknopf den echten Steam-Einladungsdialog; er wurde ohne Kontaktwahl oder Versand geschlossen. Der erfolgreiche Austausch mit zwei Konten fehlt. | Zwei Steam-Konten: Einladung, Annahme, Lobby-Beitritt und Fehlerfälle. |
| Lobby im Stil des Originalmenüs | #24/#27 schützen Host-Konfiguration und Bereitschaft nach Rejoin. #43 überträgt Auswahl, Einstellungen und Bereitschaft über den Steam-Posenpfad; die Bridge-Tests verwenden einen simulierten Link. #44 ergänzt die ImGui-Ansicht; die native 32-Bit-Stilfarbenkorrektur ist durch Regressionstest und CI geprüft. Frühere Fensteraufnahmen bestätigten die Ausgabe nicht und ein Nightly-Lauf zeigte fortlaufende D3D12-Resets. Der aktive Bildschirmtest auf #45 bestätigt jetzt die sichtbare Host-Lobby am Titelbild in 1920x1080 mit ursprünglicher Dinput8-Verknüpfung und ursprünglichen D3D12-Grafikwerten. Der native Katalogeintrag vom 11.11.2026 wurde per terminalgesteuerter Maus ausgewählt und vom Host übernommen; Kampagne und Schwierigkeit wurden angezeigt. Bereit blieb ohne Gast gesperrt. Der Einladungsbutton öffnete den echten Steam-Dialog, ohne Kontaktwahl oder Versand. hide/show und gesperrte Eingaben nach Bridge-Ende wurden geprüft. Der Test auf #45 verwendete REFrameworks geöffnetes Menü. #46 bestätigt jetzt Mausbedienung und F9 ohne Debug-Menü am Titelbild. Die eigene Inhibit-Sperre hält Maustaste beziehungsweise W nach dem Schließen bis zum Loslassen zurück; unabhängige Fensterereignisse beheben einen nativ gefundenen Fehler, den der neue Regressionstest erfasst. Ein Klick auf Spiel starten unter der Lobby blieb wirkungslos und funktionierte nach dem Schließen wieder. Der erlaubte Katalogeintrag wurde auch ohne Debug-Menü übernommen. Python- und alle Lua-CI-Suiten auf #46 sind grün. Auf #47 bestätigt ein einzelner Kampagnentest die Bewegungssperre: S für 200 ms ergab bei Erfassung 0 m über 37 frische Proben, nach F9 rund 0,073 m über 22 Proben. Zielen, Schießen, Cutscene-Eingaben, Fokuswechsel, physische Controller, weitere Auflösungen und die Gastansicht sind noch nicht abgenommen. Die Ursache der früheren Reset-Schleife bleibt ungeklärt. Originalordner und Einstellungen wurden zurückgestellt; alle zwölf erfassten Speicherdateien blieben unverändert. | Eingabesperre bei Zielen, Schießen, Cutscenes und Fokuswechseln, physische Controller, weitere Auflösungen und gleiche Bedienung/Anzeige mit zwei echten Instanzen. |
| Gemeinsames Speichern und Laden | Eigenes JSON-Checkpointformat ist kein RE2-Speicherstand. #24 prüft Host-Autorität und Konfigurationsrevision im lokalen Lobby-Modell. #43 teilt eine Slotkennung als Metadaten mit dem Gast. #45 liest optional die vorhandene native Szenario-Slottabelle, prüft die Host-Auswahl einschließlich Datumsfilter und überträgt den bestätigten Metadatenverweis. Änderungen oder Quellenverlust verwerfen beide Bereitschaftswerte. 93 Python-Tests und die aktualisierten Lua-Suiten bestehen lokal; auch die Python- und Lua-CI auf PR #45 ist grün. Im nativen Einzelinstanz-Test wurden neun Einträge gelesen, nur der erlaubte Slot 4 vom 11.11.2026 zugelassen und eine direkt eingeschleuste neuere Auswahl abgewiesen. Alle zwölf erfassten Speicherdateien blieben unverändert. Bei diesem Katalogtest wurde keine Kampagne geladen; der Metadaten-Digest bestätigt nicht den vollständigen Speicherinhalt. #47 ergänzt eine separate, ausdrücklich aktivierte Guard-/Ladeprobe. Das Originalmenü und die korrigierte asynchrone Reihenfolge luden ausschließlich den freigegebenen alten Slot bis zur Spielerwelt. Beim direkten Start vom ersten Titelbild blieb das Titel-Overlay sichtbar; `scene_loaded` ist deshalb keine Bestätigung eines nutzbaren Kampagnenstarts. Nach gesonderter ausdrücklicher Freigabe wies der installierte Guard genau eine Speicheranforderung an den gesicherten alten Slot mit `false` zurück; der Save-Manager blieb inaktiv. Alle zwölf Speicherdateien blieben bytegleich, keine neue Datei erschien. Die Originalinstallation wurde wiederhergestellt. Dieser Test bestätigt nur den konkreten Einstiegspunkt. 97 Python-Tests und acht Lua-Suiten bestehen lokal und die CI auf dem aktuellen Kopf von #47 ist grün. Weitere Menüvarianten, native Fehlerbehandlung, gemeinsame Ladebarriere und gemeinsames Speichern fehlen. #50 verwendet die nativen Menüabschlüsse und den Titelflow statt eines direkten Szenenwechsels. Vom ersten Titelbild ist eine bereinigte Spieloberfläche mit erhaltener Interaktionsanzeige in einer Instanz bestätigt. Die Kampagnenmenü-Wiederholung gilt nicht als bestanden: Nach einer abgefangenen Fortsetzen-Abkürzung stürzte eine anschließende konkrete alte-Slot-Lesung mit `0xc0000005` in `re2.exe` ab, noch vor dem neuen Menüabschluss. Ursache und Fehlerbehandlung sind offen. Weitere kontrollierte Ladeanforderungen nach einer abgefangenen nativen Ladeanforderung sind in CLI und Loader vorläufig gesperrt; dies beweist keine Absturzbehebung. Alle zwölf Speicherdateien blieben unverändert, die Originalinstallation ist wiederhergestellt. 98 Python-Tests und neun Lua-Suiten sowie die CI auf #50 bestehen. | Absturzpfad und Fehlerbehandlung isolieren; Menüvarianten in frischen Sitzungen abnehmen. Danach setzen Host und Gast denselben echten RE2-Spielstand fort. |

Der getrennte Prüfzweig #51 führt die Einzelbeiträge aus #48/#49 auf #50 zusammen, ohne offene PRs zu mergen. 104 Python-Tests und zehn Lua-Suiten sowie die CI auf dem aktuellen Kopf bestehen. Der Windows-CLI-Negativtest bei geschlossenem RE2 meldete `ready=false` und sprach keine Pipe an. Die 17-Ziel-Titelspur und die sieben Diagnose-Hooks der JSON-Ladeprobe protokollieren begrenzte durchleitende Ein-/Austritte mit ausdrücklich älteren `cached`-Statuswerten; zusätzliche diagnostische Spielabfragen laufen außerhalb der Hooks. Ein frischer nativer Titelbild-Hintergrundlauf erreichte `scene_loaded` mit passendem alten Slot, frischem Spielerobjekt, genau einer erlaubten Ladeanforderung, keiner abgefangenen Ladeanforderung und keinem erfassten Speicheraufruf. Installation und sieben durchlaufene Titel-Hookziele sowie die Reihenfolge von Titelabschluss, FINALIZE, Szenenwechsel und Ladeende sind protokolliert. Es gab keine Tastatur-/Mauseingabe oder Bildschirmaufnahme. Nach bestätigtem Prozessende wurden die Originaldateien zurückgestellt; alle zwölf Speicherdateien blieben bytegleich, keine neue erschien. Dieser Nachweis umfasst weder den sichtbaren Kampagnenmenü-Abschluss noch die Behebung des früheren Absturzes. Gemeinsame Lade-/Speicherfunktionen und alle Zwei-Instanzen-Anforderungen bleiben offen.

#54 ergänzt eine ausdrücklich aktivierte gemeinsame Dateivorprüfung und übernimmt die Einzelbeiträge von bySenom aus #52/#53/#55: unveränderte aktive Ladepolicy bei überlappenden Befehlen, getrennte Befehls-/Policy-/Lade-IDs, CLI-Warten auf den eigenen Abschluss und passende lokale Gast-Metadaten vor Bereitschaft. Der ergänzende Rücknahmetest aus der späteren #55-Integration ist ebenfalls enthalten. Die Dateivorprüfung bindet steigende Gastbestätigungen an Sitzung, Revision und Versuch; doppelte oder verspätete Bestätigungen erneuern keine Frist und können einen gescheiterten Versuch nicht wiederbeleben. Zwei simulierte Bridge-Schleifen prüfen gleiche Dateien, abweichende Bytes bei gleichen Metadaten und den Verlust der Gastbereitschaft nach erneuter positiver Prüfung. Ein realer lokaler Katalog-/Dateitest bestätigte den Hash ausschließlich der erlaubten Datei vom 11.11.2026; eine neuere Auswahl wurde abgewiesen. Dabei wurde keine Kampagne geladen; anschließend waren zwölf Speicherdateien unverändert und die Originalinstallation wiederhergestellt. Ein frischer Titelbild-Lauf bestätigte anschließend `--load --wait` für die eigene native Lade-ID. Ein zweiter, vorab datumsgeprüfter Arm-Befehl für denselben alten Slot wurde während `closing_menu` im lokalen Postfach mit `load_in_progress` abgewiesen, ohne die ursprüngliche Policy- oder Lade-ID zu ersetzen. Die erste Anforderung erreichte `scene_loaded`; eine spätere Arm-Bestätigung erhielt ihre neue Policy, während das vorherige Ladeergebnis erhalten blieb. Es blieb bei genau einer nativen Leseanforderung und keinem erfassten Speicheraufruf. Nach Prozessende wurden Originaldateien und zwölf unveränderte Speicherdateien bestätigt. Das belegt diesen Titelbild-/Überlappungspfad; andere Phasen, Kampagnenmenü, Fehlerpfad und Gast-Menüanzeige bleiben offen. 123 Python-Tests und zehn Lua-Suiten sind im kombinierten Stand geprüft; die CI ist grün. `prepared` bestätigt nur Dateibytes und gibt kein Gameplay frei. Entschlüsselung/Nutzbarkeit unter einem anderen Steam-Konto, gleicher laufender Weltzustand, gemeinsame Lade-/Speicherfunktionen und sämtliche Zwei-Instanzen-Nachweise bleiben offen. Die ursprünglichen PRs sind offen; durch die Integration wurde keine PR gemergt.

#56 begrenzt den verifizierten Gast-Lobbyzustand auf drei Sekunden seiner lokalen monotonen Uhr. Bei ausbleibenden Lobbyframes verfallen Anzeige, Befehle, Bereitschaft und Bestätigungen trotz fortgesetzter Posen/Heartbeats; die simulierte Zwei-Bridge-Prüfung und eine während des Hashens ablaufende Frist sind getestet. Der isolierte Beitrag ist in #58 enthalten. #57 bleibt ein eigener Menübeitrag auf #54: Der Autor berichtet einen nativen Multiplayer-Eintrag mit Mausklick und Eingaberückgabe auf seiner Installation. Die gemeinsame Menü-/Ladeintegration, Tastatur/Controller und Originaloption nach Rückkehr sind offen; diese fremden Messungen sind keine Prüfung auf der hiesigen Installation.

#58 liefert frische native Teilwerte für `load_header_and_inventory_core`, keine vollständige Weltgleichheit. Ladekopf-GUIDs/Kennungen und laufende Inventar-Grundwerte werden mit geprüften Schnittstellen zweimal gelesen; abweichende Daten/Objekte oder fehlende Werte erzeugen keine gültige Probe. Der Leser verlangt für eine Ladebestätigung die eigene native Lade-ID, aktive Policy, passenden Slot/Szenario und eine Beobachtung nach dem Anforderungsstart. Drei Sekunden Samplefrist und 120 Sekunden Lebensdauer der Ladeanforderung sind begrenzt; Sequenzrücksprung und VM-Wechsel für dieselbe Anforderung werden abgewiesen. Ein frischer nativer Titelbild-Lauf bestätigte fehlende Verfügbarkeit vor dem Laden, danach fünf steigende Samples mit gleichem Teil-Digest und die Abweisung einer fremden Lade-ID. Es wurde nur der erlaubte alte Slot einmal gelesen; keine Ladeanforderung wurde abgefangen und kein Speicheraufruf erfasst. Nach bestätigtem Prozessende waren Originaldateien zurückgestellt und alle zwölf Speicherdateien unverändert, ohne neue Datei. 131 Python-Tests, elf Lua-Suiten und aktuelle CI bestehen. Die 32 beobachteten temporären Datenblocktypen sind keine serialisierte oder angewandte Welt. Zusätzliche Inventardaten, Welt-/Kampf-/Story-/Cutscene-Leser, Weltstillstand, Zustandsanwendung, verifizierte Prozess-/Linkbindung und sämtliche Zwei-Instanzen-Nachweise bleiben offen. Keine PR wurde durch diese Arbeiten gemergt.

#59 baut als eigener Draft auf #58 (`561031c`) auf und erweitert den Leser um den getrennten Umfang `load_header_and_inventory_detail`: DefaultItem, AdditionalItem und ExData, Slot-Innen-/Zusatzdaten, letzter Waffentyp sowie die vier nach Richtung gebundenen Haupt-/Neben-Shortcuts. Der Kernumfang bleibt unverändert. Die Felder und lebenden Werte wurden in einer lesenden alten-Slot-Untersuchung bestätigt; dies ersetzt nicht die Abnahme des fertigen Readers. 136 Python-Tests und elf Lua-Suiten bestehen lokal; auch die [CI auf #59](https://github.com/Maaviis/re2-remake-coop/actions/runs/43737593538) ist grün. Zwei Abnahmeversuche des fertigen Readers meldeten zunächst erwartete Nichtverfügbarkeit am Titelbild und brachen dann beim Szenenladen mit `0xc0000005` im vom Framework genannten NVIDIA-Modul ab. Windows meldete zeitgleich erschöpften virtuellen Speicher (Ereignis 2004); auch ein unveränderter #58-Kernleser erreichte unter erneutem Speichermangel keinen Ladeabschluss, und ein PowerShell-Start scheiterte mit `OutOfMemoryException`. Die genaue Absturzursache bleibt offen. Nach jedem isolierten Lauf waren Originalskripte/-konfiguration zurückgestellt und alle zwölf Speicherdateien unverändert, keine neue erschien. Diese fehlgeschlagenen Versuche liefern keinen Nach-Laden-Nachweis; der spätere erfolgreiche Wiederholungslauf ist unten getrennt aufgeführt. Weitere Inventare, Itembox, Effektflags, native Anwendung und sämtliche Zwei-Instanzen-Nachweise fehlen weiterhin. Andere Anwendungen und globale Systemeinstellungen wurden nicht verändert. [INVENTORY_WITNESS.md](https://github.com/Maaviis/re2-remake-coop/blob/codex/m2-inventory-details/INVENTORY_WITNESS.md) enthält Umfang und Befunde. #57 bleibt separat; keine PR wurde gemergt.

#59 ist inzwischen auf demselben unveränderten Code nach Laden in einer frischen lokalen Instanz bestätigt: Bei wieder ausreichendem Systemspeicher meldete der Reader vor dem Laden erwartete Nichtverfügbarkeit und danach fünf frische Proben mit gleichem Detail-Digest. Erfasst wurden 20 logische Slots bei 12 nutzbaren Plätzen und je vier Haupt-/Neben-Shortcuts; 84.513 JSON-Bytes lagen innerhalb der Grenze. Eine fremde Lade-ID wurde abgewiesen. Genau eine erlaubte Leseanforderung, null abgefangene Ladeanforderungen und kein Speicheraufruf; nach Prozessende waren Originaldateien zurückgestellt und zwölf Save-Dateien unverändert, keine neue erschien. Es gab keinen Fokuswechsel oder Tastatur-/Mauseingaben. Die früheren Abbrüche sind historisch dokumentiert; ihre Ursache ist damit nicht behoben. Die Feld-/Detailabnahme in einer Instanz ersetzt weder Itembox/andere Inventare noch vollständigen Weltvergleich, Stillhalten, Anwendung oder Tests mit zwei echten Instanzen.

Der anschließende native Szenenzeitversuch bestätigt eine wichtige Grenze der Ladebarriere: `via.Scene.get_TimeScale`/`set_TimeScale(System.Single)` sind auf TDB 70 vorhanden. Bei `TimeScale=0.0` blieb der beobachtete Claire-Idle-Animationsframe über 50 frische Proben gleich, während `GameClock.get_SystemElapsedTime`, `get_GameElapsedTime`, `get_ActualPlayingTime`, `get_ActualRecordTime` und `get_InSceneTime` jeweils weiterliefen. In diesem Messfenster stiegen die fünf Rohzähler jeweils um 7.395.520 native Einheiten. Die zweisekündige lokale Testfreigabe wurde sechs Sekunden lang erneuert; nach ausbleibender Erneuerung wurde der ursprüngliche Faktor 1.0 automatisch zurückgestellt und rückgelesen. Eine erste Testfassung mit ungeeigneter Integer-Übergabe konnte die Rückstellung nicht bestätigen und wurde beendet; die korrigierte Fassung verwendet echte Lua-Gleitkommawerte und bewahrt den gelesenen Originalwert. Das ist eine begrenzte Einzelinstanz-Messung, kein Nachweis angehaltener KI, Physik, Skripte oder Cutscenes und keine Spielfreigabe. Originaldateien und zwölf unveränderte Save-Dateien wurden nach beiden Versuchen bestätigt. Der globale Weltstillstand bleibt offen; als Nächstes den vorhandenen nativen Pausenablauf einschließlich sauberer Rückkehr, Uhren und Cutscene-Verhalten prüfen, anschließend an Versuch und verifizierte Prozess-/Link-Epoche binden.

## Vorhandene Fremdmod

Die [Nexus-Dateiseite](https://www.nexusmods.com/residentevil22019/mods/3118?tab=files) und [Beschreibung](https://www.nexusmods.com/residentevil22019/mods/3118?tab=description) einer bestehenden Multiplayer-Mod nennen ein RT-Paket, Menü, Raumcode, Steam/LAN/IP und bekannte Probleme. Das sind Produktangaben, keine erfolgreiche Prüfung der geforderten vollständigen Synchronisation.

Die [Nexus-Berechtigungen](https://www.nexusmods.com/residentevil22019/mods/3118?tab=description) verlangen für Änderungen an den Dateien des Autors dessen Erlaubnis. Deshalb bleibt unsere Implementierung eigenständig. Die vorhandene Mod kann als Vergleich in einem gesonderten Testlauf dienen; ihre Skripte werden weder übernommen noch verändert.

## Fortlaufende Ladebindung (#86)

Der Livepfad prüft einen zunächst innerhalb der Ladefrist bestätigten
Ladevorgang mit unveränderten Bindungsdaten weiter. Frische Guard-,
Ladekopf-, Gegner- und Empfangsbelege bleiben erforderlich. Die lokale
Regression besteht mit 197 Python-Tests und 18 Lua-Suiten. Der native
Einzelinstanz-Test bestätigt Fortsetzung, Empfangsablauf und Erholung
bei mehr als 150 Sekunden Ladealter. Eine zusätzliche lokale Gastdiagnose
ordnet bei 412–413 Sekunden fünf echte aktive Controller zu; ihre Peerdatei
ist simuliert und ein HP-Anwender war nicht installiert. Originalinstallation
und zwölf unveränderte Save-Dateien sind bestätigt.
[LIVE_LOAD_CONTINUITY.md](LIVE_LOAD_CONTINUITY.md) dokumentiert die getrennten
Nachweise. Zwei echte Spielinstanzen und gemeinsamer Rejoin stehen aus.

## Testprotokoll für echte Spielinstanzen

Mit `--snapshot-pipe` können der Snapshot- und Gegnerabruf und die
Posen-Bridge gleichzeitig denselben REFramework-Datenordner verwenden.
Der native Buildtest prüft, dass ein Queue-Überlauf nur den betroffenen
Kanal zurücksetzt. In vier Terminalprozessen mit nachgebildeten
Windows-Pipe-Endpunkten liefen Posen in beiden Richtungen während und
nach dem Transfer eines bytegenau bestätigten 380-kB-Modells weiter.
Die gleichzeitige Spielabnahme mit zwei Steam-Konten steht aus.

Für die Zeile **Gegner, Schaden und Tod** gibt es einen
[Protokollentwurf für fragmentierte Welt-Snapshots](protocol/README.md#entwurf-für-fragmentierte-welt-snapshots).
Der Python-Test übergibt einen rund 120 KB großen synthetischen v1-Snapshot
in Paketen bis 4096 Byte und prüft die vollständige Übernahme im Modell.
Ein Terminalmodus setzt auf der bestehenden Steam-Pipe auf. Der Test mit
nachgebildetem Pipe-Gegenstück prüft den Abruf von knapp 1 MiB in Blöcken bis
acht Pakete sowie den Abbruch bei Epochenwechsel oder Prüfsummenfehler.
Der optionale Hostmodus übernimmt den nativen Gegnerbericht aus #71 nach
frischem Checkpoint-Abgleich mit dem abgesicherten Ladebeleg. Ein lokaler
Host-Gast-Test prüft den Import und erhält laufende und gespeicherte Felder
je GUID getrennt. Der Gastvergleich prüft zwei lokal abgesicherte
Ladebelege und meldet GUID-/Typ-/InheritID-Abweichungen je Quelle. Nur auf
beiden Seiten aktive, übereinstimmende Controller werden als Kandidaten
ausgegeben. Die Tests prüfen diesen Vergleich mit nachgebildeten Quellen.
Ein lesender v1-Loopback-Pfad veröffentlicht absolute HP und native
Lebens-/Todesflags der aktiven Gegner. Sein Test prüft einen empfangenden
Client, unabhängige Flags und das Verwerfen bei Quellenverlust.
Der optionale Steam-Abruf übernimmt denselben aktiven Befund nach dem
Checkpoint-Abgleich und filtert ihn nach passenden aktiven Gastobjekten.
Lokale Pipe-Tests prüfen mehrere Fragmente, ausbleibende Änderungen
und den Abbruch bei Verbindungswechsel. REFramework kann am Gast
bestätigte Beobachtungen aus einem befristeten lokalen Dateiexport mit
der aktuellen lokalen Gegnerquelle vergleichen. Der echte Titelbildtest
bestätigte Dateilesen, fehlende Szene und Fristablauf bei null Lade- und
Schreibaufrufen. Der optionale HP-Adapter verwendet den bestätigten
nativen Setter für positive HP aktiver, lebender Gegner. Ein eigenes
Testobjekt im echten Titelbild bestätigte den Aufruf und das Rücklesen von
70 auf 37. Die Tests prüfen die Zuordnung, den Schutz vor Wiederholung
und die Sperre nach einem Rücklesefehler. Die Wiederholungsprüfung trennt
jetzt die höchste empfangene Beobachtung von den je Gegner bereits
bestätigten oder versuchten Anwendungen. Vorübergehend fehlende native
Proben, wechselnde aktive Mengen oder geschützte Gegner verbrauchen den
Hostbefund nicht. Ein unveränderter, weiterhin frisch bestätigter Befund
kann nach Erholung erneut geprüft werden; ein schon behandelter Gegner
wird dabei nicht nochmals geschrieben. Auch ein Fristablauf vor dem
Schreibversuch lässt den übersprungenen Gegner erneut prüfbar. Das ist
mit simulierten Lua-Quellen geprüft. Der letzte bestätigte native
Schreibbefund bleibt mit Vorher-/Nachher-HP und Quellsequenz auch nach
Verbindungsende lesbar. Im isolierten Titelbildtest meldeten drei
native Wege auf je einer eigenen HP-Komponente bei null HP ein
wahr gesetztes Todesflag. Der optionale Lauf mit `--death-evidence`
überträgt kurze native Todesbefunde auch dann, wenn der Controller beim
nächsten Gastabruf schon fehlt. Ein Test mit nachgebildeter Pipe prüft
genau diesen Ablauf, und der Lua-Test prüft die eigene Ausgabe neben
dem aktiven HP-Abgleich. Die Anwendung und der Todesablauf an echten
Kampagnengegnern in zwei RE2-Instanzen stehen aus.

Für jeden Test: RE2-Build, REFramework-Build, Mod-Version, Steam-Konto, Host/Gast-Rolle, Spielstand, Szenenkennung und Zeitstempel erfassen. Jede Instanz protokolliert lokal dieselben stabilen Objekt-IDs und Zustandswerte. Ein Test gilt nur dann als bestanden, wenn beide Wertefolgen nach definierter Latenztoleranz übereinstimmen und nach Wiederverbindung gleich bleiben. Für Cutscenes müssen Beginn, Fortschritt, Skip und Ende einzeln verglichen werden.

Ein zweiter PC mit eigenem Steam-Konto ist laut Nutzer derzeit nicht verfügbar. Ohne zwei gleichzeitig gestartete RE2-Instanzen, zwei Konten und lesbare Zustandsmessung bleibt der Spielnachweis offen. Unabhängig davon bleiben die Fehlerbehandlung und die Kampagnenmenü-Abnahme aus #50, Fokus-/Ziel-/Schussprüfungen, der native Kampagnenmenü-Vergleich des in #51 integrierten Prüfstandes und anschließend die gemeinsame Ladebarriere möglich. #54 liefert deren Dateivorprüfung; #58 ergänzt den begrenzten nativen Ladekopf-/Inventarkernbeobachter und den Gast-Fristfix aus #56. #59 bestätigt inzwischen nach Ressourcenentspannung den getrennten Inventar-Detailumfang nach Laden in einer Instanz. Der Szenenfaktor allein hielt die beobachteten Uhren nicht an; der native Pausenablauf mit sauberer Rückkehr ist als Nächstes zu prüfen; weitere Inventar-/Weltleser und die Prozess-/Linkbindung fehlen weiterhin. Die sichtbare Menüabnahme wartet auf einen passenden Vordergrundtermin. Der Menübeitrag #57 bleibt separat zu integrieren. Ein vollständiger gemeinsamer nativer Zustand und eine Spielfreigabe sind damit nicht hergestellt. #48 liefert einen lesenden Preflight mit bestätigten Sololauf-Negativbefunden; der positive Zwei-Rechner-Nachweis fehlt. #49 liefert die passive Ablaufspur auf der tatsächlichen Basis #47. Je Spielinstallation wird ein nativer Testführer mit seiner gestarteten Prozess-ID protokolliert; Testordner dürfen nicht gleichzeitig verändert und fremde Instanzen nicht beendet werden. Die sichtbare Host-Ausgabe ist für 1920x1080 bestätigt; weitere Anzeige- und Eingabefälle bleiben zu prüfen. Lokale Spieltests verwenden ausschließlich die freigegebenen Spielstände vom 11.11.2026; die Spielsteuerung erfolgt nur über das Terminal.
