# Arbeitsplan: RE2 Remake Koop

## Fortsetzen nach Sashas Integration: Abbruch prüfen (E2)

Sasha hat #173 mit Kopf `ef86a91` übernommen und in `d0c85ac` den
Archivtransfer und gemeinsamen Fortsetzen-Controller angebunden. Dieser
Folgezweig baut auf main `c9c4bce` auf. Der lokale Abbruch widerruft jetzt
im echten `CheckpointStartController` den eigenen Beleg, bevor er auf den
Kampagnen-Worker wartet und seine Ressourcen freigibt. Er erhält eine
inzwischen ersetzte Vorbereitung und verändert das Archiv nicht.

Build `873368c` besteht 532 Pythonfälle, 38 Lua-Suiten und 90 Tests aus
seinem tatsächlichen 121-Dateien-Steam-ZIP (E2). Als Nächstes den integrierten
Controller in echtem RE2 prüfen; der bisherige positive E3-Nachweis gehört
weiter zu `17d862e`. Normaler Steam-Neustart, neue Lobby und zwei verschiedene
Konten bleiben Abnahmebestandteile. Keine weitere Hauptbranch-Integration
ohne Sashas Entscheidung.
[E2-Nachweis](../../validation/checkpoint-controller-cancel-2026-11-27.json).

## Archivgebundener Ladeauftrag: übernommene Grundlage (E2/E3)

Die übernommene Grundlage implementiert die lokale Schema-5-Policy, die native
Vormerkung und Zulassung sowie den anschließenden Pausen-/Checkpointvergleich.
Archiv-Digest und gemeinsamer Versuch bleiben gleich; lokale Referenzen und
Vorbereitungsnonces dürfen abweichen. Ein abgelöster oder abgelaufener Beleg
kann weder die alte Policy ersetzen noch einen nativen Start wiederbeleben.
Der explizite lokale Starter reicht Slot 0 an die vorhandene Freigabe und
den Kampfkanal weiter. Der Weltvergleich prüft zusätzlich die Schwierigkeit
der ausgewählten Generation. Unterbrechungen behalten die originale Bindung.

498 Python-Fälle und alle 37 Lua-Suiten bestehen lokal (E2). Die Kopf-CI
von `17d862e` ist grün: 501 Pythonfälle, 38 Lua-Suiten, acht native CTests,
76 Windows-Pythonfälle und 101 Tests aus dem CI-Steam-ZIP. Die CI prüft
den synthetischen Merge `dc24dba`; dessen 119-Dateien-Paket ist E2 geprüft.
[E2-Nachweis](../../validation/checkpoint-schema5-regression-2026-11-27.json).

Der lokale Build `17d862e` (117-Dateien-Steam-ZIP) bestätigt zusätzlich
in echtem RE2: isoliertes Profil ohne Szenariosaves, Archivimport,
8,437 Sekunden/acht Erneuerungen, produktive Schema-5-Policy, native
Vormerkung und nach modellierter gemeinsamer Startfreigabe genau einen
Load bis Slot 0/Leon A/Standard/Karte 174/Gebiet 0. Ladekopfzeuge und
native Pause sind bestätigt. Originalsaves, Originalprofil, Steam-Cache
und ACL sind geprüft zurückgesichert. Der private Treiber veröffentlicht
seine modellierte Lobby nun unabhängig von den langsamen Prüfungen;
die produktiven Drei-Sekunden-Schutzfristen bleiben unverändert.
[E3-Komponentenmessung](../../validation/native-checkpoint-schema5-policy-2026-11-27.json).

Der genannte E3-Lauf verwendete eine Hostinstanz und ein Konto mit
modelliertem Gast/Start und endete an der nativen Pause. Die automatische
Menü-/Controller-Anbindung ist seit `d0c85ac` in main enthalten und zunächst
E2 geprüft. Die bisherigen E3-Nachweise behalten ihre Quellbuilds. Der
konkrete Controllervertrag steht in
[CHECKPOINT_POLICY_V5.md](../campaign/CHECKPOINT_POLICY_V5.md).


Der explizite Checkpoint-Aufruf des nativen Loaders ist jetzt auf der aktuellen
main-Struktur in echtem RE2 nachgewiesen (E3, `2ca28ce`). Das tatsächliche
117-Dateien-Steam-ZIP lieferte die nativen und Lua-Komponenten; 52 Python-Tests
bestehen aus dessen eingebetteter Laufzeit. Eine isolierte Kopie nur mit
Systemdaten bestätigte vor dem Mount zweimal null Szenariosaves. Import,
acht Sekunden Bereitschaft mit acht Erneuerungen und der produktive lokale
Loader-Aufruf ohne Freigabeadapter erreichten im selben Prozess Slot 0,
Leon A, Standard, Karte 174/Gebiet 0 und native Pause: ein erlaubter,
kein verweigerter Load. Elf Originalsaves blieben separat gesperrt;
Originalprofil, Dateibestand, Prüfsummen, Steam-Cache und ACL sind geprüft
zurückgesichert. Lobby und Gast waren modelliert. Gemeinsame Ladepolicy,
Steam-Neustart/neue Lobby und zwei Konten sind weiterhin offen.
[Messbericht](../../validation/native-checkpoint-current-main-loader-2026-11-27.json)


## Integrationsentwurf für Fortsetzen

`codex/checkpoint-continue-controller` bereitet die Bausteine aus #157
auf main `794ea7f` vor. Laufzeitmodule liegen entsprechend der aktuellen
Struktur unter `bridge/`, technische Dokumentation unter `docs/`. Die sieben Konflikte sind auf diesem eigenen
Entwurfszweig aufgelöst: vorhandene Archivwahl, Belegleser mit Wiederholung,
Frame-/Hintergrundtransport, Gastvorbereitung, Bewegung und Inventar-Neuladen
bleiben aus main erhalten. 89 gezielte Python-Tests, 37 Lua-Suiten und acht
native CTestfälle bestehen; beide Plugins sind neu gebaut (E2).

Der lokale Checkpoint-Loader dieser Zusammensetzung ist mit `2ca28ce`
in E3 geprüft. Der vollständige gemeinsame Continue-Ablauf ist offen.
Die älteren E3-Messberichte behalten ihre ausdrücklich genannten #157-Builds. Als Nächstes wird der archivgebundene Ladeauftrag
als konkreter gemeinsamer Entwurf vorbereitet. Sasha entscheidet über
die Schnittstelle und Übernahme; #157 bleibt als Baustein-PR erhalten.

## Speichern und Fortsetzen

Die Voraussetzung eines Profils ohne alte Szenariosaves ist jetzt auch
in echtem RE2 geprüft (E3, `783d39e`). Eine verwaltete isolierte Kopie
enthielt ausschließlich Systemdaten. Vor dem Kampagnen-Mount bestätigte
der erneuerte native Katalog zu zwei verschiedenen Zeiten null Szenarios.
Import, Bereitschaft und derselbe lokale Load erreichten danach Leon A,
Standard, Karte 174/Gebiet 0 mit Pause. Der gesicherte Originalbestand
mit elf Dateien blieb gesperrt; Originalverzeichnis, Bestand, Prüfsummen
und Steam-Dateicache sind zurückgesichert. Native Steam-Rolle war Host
auf demselben Konto; dies ersetzt keine echte Gast-/Zwei-Konten-Abnahme.
[Messbericht](../../validation/native-checkpoint-empty-profile-2026-11-27.json)

Die lokale Bereitschaft lässt sich jetzt während des Wartens am Titel
erneut vollständig prüfen. `CheckpointReadiness.refresh()` erneuert nur
einen noch gültigen eigenen Vorbereitungsbeleg; Archiv-/Arbeitsdateien,
nativer Import, Katalog, Prozess und Lobby werden erneut bestätigt.
E3 mit `783d39e` wartete rund neun Sekunden mit acht Erneuerungen und
lud danach denselben Checkpoint mit demselben Nonce bis zur nativen Pause.
Archiv, zwölf Original-/Cachedateien und ACL-Rücksicherung sind geprüft.
[Messbericht](../../validation/native-checkpoint-readiness-2026-11-26.json)

Der Controller muss regelmäßig am Titel erneuern und vor dem nativen
Load damit aufhören. Ein Ablauf oder Quellenverlust verlangt eine neue
Vorbereitung. Es gibt noch keine automatische Anbindung an Continue.
Der konkrete Ladevertrag wurde Sasha (@bySenom) zur Abstimmung mit dem
anderen Entwickler direkt in [#157 übergeben](https://github.com/Maaviis/re2-remake-coop/pull/157#issuecomment-7205032377).
Die gemeinsame Schnittstelle liegt als Schema-5-Reviewentwurf vor;
ihre Übernahme bleibt offen.

Die getrennte Fortsetzen-Vorbereitung ist mit `e32622e` in echtem RE2
bestätigt (E3). `CampaignSetup.enable_checkpoint(selection, revision)`
beginnt am geschützten Titel ohne Kampagnen-Mount, öffnet den bestehenden
Ordner der gewählten Archivkampagne und führt Import und Katalogerneuerung
aus. Der private Loader-Adapter erreicht danach im selben Prozess Leon A,
Standard, Karte 174/Gebiet 0 und die native Pause. Kein zusätzlicher
Arbeitsordner entstand; Archiv, zwölf Original-/Cachedateien und
ACL-Rücksicherung sind geprüft. Der gemeinsame Menü-/Ladeauftrag bleibt
zur Abstimmung mit Sasha offen.
[Messbericht](../../validation/native-checkpoint-setup-2026-11-26.json)

Der zusätzliche lokale Ladebaustein ist mit `329c22b` in echtem RE2
bestätigt (E3): Import, Katalogerneuerung und Slot-0-Load laufen im
selben Prozess. Die Welt erreicht Leon A, Standard, Karte 174, Gebiet 0
mit Spielfigur und bestätigter nativer Pause. Ein erlaubter und kein
abgewiesener Ladeaufruf; Archiv und zwölf Originaldateien bleiben geprüft.
Der private Treiber verwendet die neue begrenzte Guard-Zulassung und
einen Adapter für den vorhandenen Loader. Die gemeinsame Ladepolicy und
die Fortsetzen-UI sind noch nicht umgestellt.
[Messbericht](../../validation/native-checkpoint-inprocess-resume-2026-11-26.json)

Als Nächstes stimmt Sasha den gemeinsamen Ladeauftrag auf diese lokale
Zulassung ab: Checkpoint-Digest, Vorbereitungsnonce und lokale Referenzen
müssen an denselben Versuch und beide nativen Pausen gebunden bleiben.
Die Einbindung des Gasttransfers, normaler Steam-Neustart und E4 stehen
weiterhin aus.

Der Steam-Export auf `eec876a` enthält nun auch den benötigten
Katalogbaustein. E3 mit den Komponenten aus dem tatsächlichen ZIP
bestätigt Import und Katalogerneuerung im selben RE2-Prozess. Die
frühere 104-Dateien-ZIP-Fassung enthielt diesen Baustein nicht; der
damalige E3-Lauf verwendete das vollständige Testpaket.
[Exportprüfung](../../validation/native-checkpoint-steam-export-2026-11-26.json)

Die lokale Gastübernahme `GuestCheckpointArchive` ist als unabhängiger
Baustein ergänzt (E2). Sie setzt keinen alten Szenario-Spielstand voraus
und veröffentlicht nur drei vollständig geprüfte Dateien samt Manifest.
`checkpoint_transfer` verbindet diesen Empfang jetzt mit dem vorhandenen
Snapshot-Kanal (E2). `ArchiveTransferBinding.exchange(request_id)` bindet
Quelle und Ziel an dasselbe aktive geschützte Profil, die vollständige
Lobbyauswahl und die native Steam-Peer-Epoche. 32 gezielte Tests bestehen,
darunter Übertragung über 1 MiB, beschädigte Bytes, Quellen-/Auswahlverlust,
Epochwechsel und Abbruch nach Transferbeginn. Gast-Einzelspielerdateien,
Arbeitsordner und ältere gültige Generationen bleiben dabei erhalten.
Als Nächstes Capability-Aushandlung und den gemeinsamen Fortsetzen-Auftrag
mit Sasha abstimmen und an diesen optionalen Baustein anbinden. Die
Übernahme selbst lädt keine Welt; zwei echte Steam-Konten sind ungeprüft.

Der Entwickler für Speichern und Fortsetzen liefert die native
Slot-0-Erfassung und das Archiv in #157. Die bisherige E3-Prüfung
belegt einen neuen nativen Checkpoint und seinen Weltübergang in
einer frischen Instanz. Speicherzeitpunkt und aktuell aus dem
Archivbestand gelesene Slotreferenz sind getrennt zu prüfen.

Die wiederholte native Erzeugung und die Archivierung über die produktive
Host-Bridge sind mit `68c9535` in einer RE2-Instanz geprüft. Ein Abbruch
nach Annahme der zweiten nativen Speicheranforderung ließ die erste und
vier ältere Generationen unverändert. Der private Test hielt dafür den
nächsten Update-Schritt kurz an; die Gastrolle war simuliert. Die Details
und Grenzen stehen im Messbericht vom 26. November.

Die Vorbereitung einer ausgewählten Archivgeneration ist mit `e2427de`
in einer geschützten RE2-Instanz bestätigt (E3). Die Bridge übergibt nur
die drei geprüften Dateien an den bestehenden nativen Schreibschutz.
Echte Steam-Abschlüsse, Datei-Prüfsummen und derselbe aktive Mount sind
bestätigt. Der native Katalog wurde im selben Titelprozess auf den
gewählten Leon-Checkpoint aktualisiert. Das Archiv blieb unverändert.
Lobby-Modell und Gegenstelle waren simuliert; es wurde keine Welt geladen.

`b589a03` ergänzt die reguläre Katalogerneuerung. Ein weiterer E3-Lauf
verwendet die unveränderten ausgelieferten Guard-/Katalog-Autoruns;
der private Lua-Treiber beobachtet nur. Der Vorbereitungsbeleg enthält
jetzt die nach der Erneuerung zweimal gleich gelesene lokale Slotreferenz
und ist an Prozess, Mount, Lua-Lauf und Importanforderung gebunden.
[Autorun-Messbericht](../../validation/native-checkpoint-catalog-autorun-2026-11-26.json)

Als Nächstes die neu erfasste lokale Referenz beider Rollen an die
Archivprüfsumme und den vorbereiteten gemeinsamen Ladeversuch binden.
Der bisherige Aufruf `save_guard.allow(local_native_reference)` bleibt
mit `isolated_new_game_required` gesperrt. Die oben geprüfte zusätzliche
Zulassung setzt eigene frische Belege voraus. Die Vorbereitung allein
erteilt keine Ladefreigabe. Die Arbeitsordner sind wegen der Steam-Dateiquote begrenzt
wiederzuverwenden; unvollständige Importe dürfen keinen bestätigten
Checkpoint ersetzen. [Messbericht](../../validation/native-checkpoint-workspace-2026-11-26.json)

Sasha stimmt die Fortsetzen-Auswahl und den zusätzlichen Ladeübergang
im laufenden Koop-Mount mit dem Entwickler von #155 und #156 ab.
Der bestehende Aufruf `arm(..., prepared_lobby=...)` weist Slot-Laden
in diesem Mount derzeit ab. Der neue Übergang muss die Checkpoint-
Prüfsumme an die lokalen nativen Referenzen beider Rollen und die
gemeinsam bestätigte Szene binden. Danach auf zwei PCs den normalen
Steam-Start, eine neue Lobby und den Gast ohne passenden alten
Einzelspieler-Slot abnehmen. Die Testfolge steht in SHARED_LOAD.md.

## Kampagnenstart und Verbindungsverlust

Maaviis/Codex prüft den Kampagnenstart mit Bestätigungen der tatsächlich
aufgehobenen Pause auf beiden Seiten. Bei fehlender Bestätigung oder
Verbindungsverlust kann derselbe Spielkontext erneut angehalten werden.
Der alte Startbefehl verliert seine Wirkung. Für die Zwei-PC-Abnahme
zuerst die Bestätigung und den Abbruch in beiden Rollen prüfen. Beim
Wiederbeitritt muss vor einer neuen Freigabe der Weltzustand abgeglichen
werden. Der Vergleich deckt aktuelles Gebiet, Spielerinventar, Ladekopf,
zwei getrennte Gegnerwerte, Türen der geladenen Szene und native
Gegenstandsdaten ab. Ein geschützter Einzeltest hat Spieler-Kollisionen
und die gezielte native Aktivierung des zugehörigen Triggers bestätigt.
Als Nächstes den nachgelagerten `FeedbackFSM`-Ablauf bis zur Aufnahme
beobachten und den Übergang im Inventar sowie am Fundort abgleichen.
Danach folgen Rätsel, Skripte, Zwischensequenzen und die Anwendung
des Hostzustands am Gast. Automatisierte Teststarts nutzen den separaten
Windows-Desktop und bleiben während des gesamten Laufs getrennt.

Der aktualisierte Zweig von bySenom in #136 bringt den Gegnerabgleich
für lebende Gegner und geprüfte Gasttreffer mit. Maaviis/Codex führt
ihn mit der beidseitigen Startbestätigung und dem Wiederbeitrittsvergleich
zusammen. Zur nativen Zwei-PC-Abnahme gehören auch Treffer in beiden
Rollen, Raumwechsel und der Ausfall des Kampfkanals bei weiter
verbundener Steam-Lobby.

Für Zombie-Tod überträgt der Host den abgeschlossenen nativen Callback
mit unabhängiger Zustandsbestätigung. Maaviis/Codex prüft danach den
natürlichen Trefferpfad und die Anwendung beim Gast einschließlich
Killzähler, Körperzustand, Beute und Skriptnebenwirkungen.
Der separate `applyDead()`-Versuch am Standby-Gegner bestätigte die
Rückkehr bei unverändertem gespeichertem Gegnerzustand. Der nächste
native Referenzlauf braucht einen regulär simulierten Gegner und einen
gewöhnlichen tödlichen Treffer.
[Messwerte](../../validation/native-death-transition-2026-11-22.json)

## Gemeinsame Schutz- und Ladeintegration (20. November 2026)

Der Quellenstand verbindet #103 mit #117: Jeder Ladebefehl braucht die
frischen, an denselben RE2-Start gebundenen Schutzbelege. Vorbereitete Loads
behalten zusätzlich die aktive Steam-Verzeichnisprüfung, deaktivierte Cloud
und den laufenden Windows-ACL-Schutz. Die native Pause und beide Phasen des
Checkpoint-Abgleichs verlieren ihre positive Freigabe bei Schutzverlust.
Die Pause bleibt dabei bestehen. Ein lokaler nativer Load-, Plattform-Schreib-
und Pausentest dieses Standes bestand am 20. November; Einzelheiten und
Grenzen stehen in [SAVE_PROTECTION.md](../campaign/SAVE_PROTECTION.md). Gemeinsames Laden
mit zwei Konten und ein neues geprüftes Paket für beide Rechner stehen aus.
Die ursprüngliche Installation wurde nach dem temporären Lauf wiederhergestellt.

## Lesende Timeline-Messung (17. November 2026)

Maaviis/Codex ergänzt auf #104 einen getrennten, optionalen nativen Leser
für Timeline-Aktivität. Kameraereignisse, Inhaltskennungen, echte
Timeline-Frames und Audio-Zähler bleiben getrennt; widersprüchliche
Doppelabfragen werden verworfen. Der native Einzelinstanz-Test bestätigt
den fertigen Leser nur ohne aktive Zwischensequenz. 233 Python-Tests und
20 Lua-Suiten bestehen. [TIMELINE_ACTIVITY.md](../observers/TIMELINE_ACTIVITY.md)
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

## Ladepause im vorbereiteten Versuch (17. November 2026)

Maaviis/Codex ergänzt auf dem getrennt geprüften Stand #102 eine eigene
native Pause für den bereits zugelassenen Ladevorgang. Ein positiver
Checkpoint-Abgleich verlangt denselben frischen Pausennachweis in beiden
Transferphasen. Die Komponente beendet die Pause nicht automatisch bei
Peerverlust oder Zeitablauf. Der native lokale Negativtest ohne Gegenstelle
bestätigt die Pause und drei stillstehende Simulationsuhren; er liefert
ausdrücklich keinen gemeinsamen Checkpoint. Details:
[PREPARED_LOAD_PAUSE.md](../campaign/PREPARED_LOAD_PAUSE.md).

Als Nächstes sind die beiden echten Pausen mit zwei Konten, die noch
unbestätigten Welt-Subsysteme und die abgestimmte Spielfreigabe zu prüfen.
Die Freigabe darf nicht allein aus einem passenden Ladekopf folgen.
Kampf, KI, Physik, Skripte, Inventare und Cutscenes brauchen weiterhin
vollständige native Zustandsanwendung und eigene Zwei-Instanzen-Nachweise.
Die Quellenintegration der Schutzverfahren aus #102 und #103 ist oben
beschrieben. Das zuvor geprüfte Nutzerpaket `4494ef2` bleibt unverändert.

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
[ENEMY_ACTIVITY.md](../observers/ENEMY_ACTIVITY.md) grenzt Befund und Folgearbeit ab.
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
ist geschlossen. [DEATH_OBSERVER.md](../observers/DEATH_OBSERVER.md) hält Grenzen und die
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
Erweiterungen sind entfernt. [NATIVE_CAMPAIGN_HP.md](../observers/NATIVE_CAMPAIGN_HP.md) und die dort
verlinkten bereinigten Ergebniswerte grenzen den Nachweis ab.

Nächste Kampfabnahme: natürlicher Treffer, Todesablauf und Nebenwirkungen
an echten Kampagnengegnern, danach der beidseitige Test mit zwei PCs. Der
Freund ist später verfügbar; bis zu seinem Termin wird an den unabhängigen
Engine-Pfaden weitergearbeitet. Das installierte Verbindungspaket bleibt
unverändert. #104/#105 sind getrennte Lade-/Timeline-Entwürfe und nicht in
diese Schutzfassung integriert. Vollständige Koop-Synchronisation bleibt offen.

## Vorrang: Speicherschutz und neue Testinstallation (17. November 2026)

Maaviis/Codex übernimmt die Korrektur nach dem nachgewiesenen Autosave-Fehler. Die Originalsaves wurden lokal zurückgesichert und von Steam automatisch wieder vollständig hochgeladen; die alte Testinstallation und das alte Paket sind zurückgezogen. Die neue Paketfassung `4494ef2` ist installiert und mit portablem Python sowie beiden nativen Plugins geprüft: Host-Lobby, lesender Load des erlaubten alten Slots, frische Spielerpose und Gaststart ohne Einladung. Nach beiden getrennten Einzelinstanz-Läufen blieben zwölf Save-Dateien unverändert. [TEST_PACKAGE.md](../testing/TEST_PACKAGE.md) hält Umfang und Bedienung fest; [SAVE_PROTECTION.md](../campaign/SAVE_PROTECTION.md) den Sicherheitsbefund. Offen sind zwei echte Steam-Konten und die Abnahme nativer Autosave-Schreibpfade. Keine weiteren Kampagnen-/Kampftests mit dem alten Paket. Die parallelen #93–#102 sind nicht Teil dieses Pakets; insbesondere müssen der ACL-/Cloud-Prüfpfad aus #95/#100–#102 und die Belege aus #103 vor einer späteren Integration gemeinsam abgeglichen werden. Keine dieser getrennten Fassungen allein gilt als integrierte Zwei-Spieler-Abnahme.

## Ziel und Stand

Ziel ist eine eigenständige Zwei-Spieler-Mod mit nachweislich gemeinsamem Spielzustand über die gesamte Kampagne. Die gemeinsame Entwicklungsbasis aus #62 enthält Steam-/REFramework-, Menü-, Lade-, Inventar- und Pausenbausteine. Einzelinstanz- und Prozessnachweise liegen vor; zwei echte Spielinstanzen wurden noch nicht gemeinsam geprüft. Eine spielbare Koop-Kampagne existiert noch nicht. [STATUS.md](STATUS.md) führt Anforderungen und Prüfgrenzen auf.

Eine veröffentlichte Fremdmod dient nur als Vergleich; ihre Dateien oder Assets werden wegen der veröffentlichten Änderungsrechte nicht übernommen.

## Aktuelle Aufgaben nach der Zusammenführung

Aktuelles getrenntes Kampf-Arbeitspaket zu [#2](https://github.com/Maaviis/re2-remake-coop/issues/2): den passiven GUID-/Schadenscallback aus [DAMAGE_OBSERVER.md](../observers/DAMAGE_OBSERVER.md) an einem regulären echten Gegnertreffer bestätigen, gegen native HP/Todesflags/Killzähler abgleichen und erst danach an Checkpoint und Hostereignisse binden. Native Hookinstallation und begrenztes Zielen/Schießen sind in einer Instanz belegt; der positive Treffer bleibt offen. Die installierte Testfassung auf #87 wird durch diesen Forschungszweig nicht automatisch ersetzt.

[PR #62](https://github.com/Maaviis/re2-remake-coop/pull/62) ist in `main` enthalten, einschließlich #8–#61 sowie #63 und #67. #68 ist nach ausdrücklicher Nutzerfreigabe ebenfalls in `main` und ergänzt die lesende Menü-Vorprüfung vor einer Einladung. Die ursprünglichen Kopfcommits wurden abgeglichen; die 29 danach noch offenen Stapel-PRs sind mit Integrationsverweis geschlossen. Die Basis muss nicht erneut zusammengeführt werden. [AKTUELLER_STAND.md](AKTUELLER_STAND.md) erklärt den Stand; [INTEGRATION_REVIEW.md](INTEGRATION_REVIEW.md) hält die Prüfung fest.

#60 bestätigt den nativen Gameplay-Pausenpfad in einer Instanz: Die beobachtete Animation und tatsächlichen Spiel-/Rekord-/Szenenzeiten standen still; `PauseBehavior.toReturnGame()` schloss Menü und Flow vollständig. Diese Teilabnahme ersetzt weder vollständigen Weltstillstand noch die verteilte Ladebarriere. Die spätere native Menüprüfung aus #67 ist in LOBBY_MENU.md dem jeweiligen Autor zugeordnet. Der derzeit nicht mögliche Vordergrundtermin wird nicht als Testnachweis gewertet.

Der optionale Gegnerleser bestätigt 55 registrierte und 87 separat gespeicherte Datensätze (91 GUIDs insgesamt). Die neue Einzelinstanz-Messung erfasst fünf aktive Controller sowie eine native HP-Folge 770 → 769 → 0. Beim Ausstreamen übernimmt der Speicher die 0 HP; nach erneutem Einstreamen bleiben GUID und HP-/Todesflags an neuen konkreten Controller-/HP-Objekten erhalten. Der Killzähler bleibt 19. [ENEMY_WITNESS.md](../observers/ENEMY_WITNESS.md) grenzt Komponentenaufrufe, reguläre Treffer-/Todesnebenwirkungen und den noch offenen Zwei-Instanzen-Nachweis ab. Die getrennten Transport-/Gastentwürfe ab #73 werden eigenständig geprüft.

**Maaviis/Codex übernimmt als nächsten Integrationsschritt [#86](https://github.com/Maaviis/re2-remake-coop/issues/86):** Die laufende Gegnerbeobachtung über die bisherige 120-Sekunden-Ladegrenze hinaus an denselben bestätigten Ladevorgang binden. Frische Guard-/Quell-/Empfangsbelege, Sitzungs-/Lade-/Objektzuordnung und Wiederholungsschutz bleiben erforderlich. Für Kampf/Welt folgen reguläre Treffer samt Killzählung und Nebenwirkungen; danach der gemeinsame Nachweis mit zwei echten Instanzen.

| Zuständiger Bereich | Nächste konkrete Lieferung | Abhängigkeit und Abnahme |
|---|---|---|
| Integration und Qualitätssicherung | Konsolidierten Stand reproduzieren; Python/Lua und Windows-Plugin dauerhaft in CI prüfen; neue PRs gegen `main` vergleichen | Automatische Prüfungen grün; Einzelinstanz und Zwei-Instanzen-Nachweise getrennt |
| RE2-Spieler/Kampf und Welt | Stabile Gegner-/Objekt-IDs, Treffer, Schaden, Tod, Items, Türen, Rätsel und weitere Inventare lesen; danach native Anwendung ohne Echo-Schleifen | Erst lokale Engine-Nachweise, danach beide echte Instanzen mit identischen Ereignisfolgen |
| Skripte und Zwischensequenzen | Kampagnenflags und Szenenmatrix für Start, Ablauf, Skip und Ende erfassen; Verhalten unter nativer Pause messen | Keine vollständige Pause oder Synchronisation allein aus Uhren-/Idle-Messungen ableiten |
| Speichern und Wiederherstellung | Vollständigen nativen Zustand definieren/anwenden; an Ladeversuch, Prozess, Steam-Sitzung und Link-Epoche binden; gemeinsame Freigabe und Rejoin | Bisherige Dateivorprüfung/Teil-Digests genügen nicht; früheren Fortsetzen-Absturzpfad isolieren |
| Lobby und Steam | Erstellen, Einladung, Bestätigung und Handshake mit zwei Konten prüfen; Gastbedienung und Fehlerfälle abnehmen | Zweiter PC/Konto derzeit nicht verfügbar; Tastatur/Controller und weitere Eingabefälle bleiben offen |

Die Bereiche sind Arbeitspakete, keine neu zugesagten personellen Zuweisungen. Bestehende Beiträge von bySenom und Maaviis/Codex sind unten dokumentiert. Vor der nächsten Schnittstellenänderung wird das passende Issue übernommen. Zwei echte Spielinstanzen bleiben für jede Gameplay-Kategorie erforderlich. Lokale Tests verwenden ausschließlich die freigegebenen Spielstände vom 11.11.2026 und Terminalsteuerung.

Aktueller Prüfauftrag für **Maaviis/Codex / Integration und Kampf**:
Den positiven HP-Entwurf aus #80 samt Fristprüfung und Schreibbelegen
aus #81 gegen vorübergehenden Quellenverlust,
später aktive Gegner und unveränderte Hostbestätigungen absichern.
Wiederholungen je Gegner behandeln, ältere Beobachtungen sperren und
fehlgeschlagene Schreibversuche weiterhin abschalten. Die lokale
Regression ist von der noch offenen Anwendung an echten
Kampagnengegnern und dem Zwei-Instanzen-Nachweis zu trennen. #71 bleibt
die getrennte native Leserabhängigkeit; die Transportarbeit aus #73–#79
wird dadurch nicht ersetzt.

**Maaviis/Codex / #86:** Die laufende Gegnerbeobachtung nutzt nach ihrer Erstprüfung eine weiter frisch geprüfte Ladebindung. 197 Python-Tests, 18 Lua-Suiten sowie getrennte native Host-/Gastdiagnosen nach mehr als 120 Sekunden sind bestätigt; [LIVE_LOAD_CONTINUITY.md](../campaign/LIVE_LOAD_CONTINUITY.md) grenzt die lokal erzeugten Peerbelege ab. Nächste Abnahme: echte Host-/Gastinstanzen mit länger laufender Sitzung, Quellenverlust und erneutem Zustandsvergleich. Prozessneustart und gemeinsamer Rejoin bleiben gesondert offen.

## Historische Einzelbeitragsprotokolle

Die folgenden Angaben zu damaligen Drafts, offenen PRs und Integrationsschritten beschreiben ihren jeweiligen Zeitpunkt. Für den aktuellen Stand gilt der Abschnitt oben.

## Aktualisierte Aufgabenfolge (15. November 2026)

Die Entwicklungszweige reichen inzwischen bis #59; ihre Freigabe und die noch fehlenden nativen Nachweise bleiben offen. #22 beobachtet Animationsbank, Clip und Frames des Kampagnenspielers; #23 spielt einen installierten Leon-Idle-Clip auf einem eigenen sichtbaren Testobjekt ab. #24 sichert die Host-Autorität im lokalen Lobby-Modell. #25 trägt Animationsdaten durch die v1-Posenkette; das native Lesen und die Übertragung einer Claire-Probe bis zur Gastdatei wurden in einer Spielinstanz bestätigt. #26 rendert optional einen empfangenen Leon-Idle-Clip auf einem eigenen Testobjekt; ein nativer Einzelinstanz-Test mit synthetischer Gastpose bestätigte diesen Clip, echte Leon-Sendedaten und zwei Instanzen stehen aus. #27 verwirft veraltete Bereitschaft nach Wiederbeitritt. #28 bis #30 prüfen private Steam-Lobbys, Einladungseingang und einen Nachrichtenkanal im laufenden RE2; ein echter Roundtrip zwischen zwei Konten steht aus. #31 erprobt eine relative Clip-Phasenangleichung als Entwurf, bisher nur mit Lua-Tests und bestätigter Engine-Methode. #32 verbindet die autoritative v1-Posenübertragung mit bestätigten Steam-Lobby-Teilnehmern; Prozess- und Einzelinstanz-Tests liegen vor, der Austausch zweier echter Spielinstanzen fehlt. #33 ergänzt frische Start- und Stop-Anweisungen für die Motion-Diagnose aus dem Terminal; der native Test steht aus. #34 erprobt für den Steam-Posenpfad eine lokale Empfangsfrist statt des direkten Vergleichs zweier Rechneruhren; der simulierte Uhrversatz ist getestet, der Zwei-Rechner-Nachweis fehlt. #35 lässt die laufende Gast-Bridge nach einem Host-Bridge-Neustart und geprüftem `hello` eine neue Sitzung übernehmen; der Prozess-Test besteht, der native Nachweis fehlt. Diese Probes ersetzen keinen Zwei-Spieler-Nachweis. #21 baut auf #20 sowie früheren Entwürfen auf. Sein zuvor gemeldeter Dokumentationskonflikt ist behoben; GitHub meldet den Entwurf wieder als zusammenführbar. Ein neuer Host-Test prüft, dass ein nicht lesender Peer den Ereignisversand an andere Peers nicht blockiert. Die Basis `main` enthält die neueren Funktionen noch nicht. Vor weiteren Gameplay-Arbeiten wird die PR-Kette in Abhängigkeitsfolge geprüft, die Tests je Integrationsschritt ausgeführt und die Zweig-Abhängigkeiten aufgelöst. Keine der offenen Arbeiten gilt allein durch einen bestandenen CI-Lauf als im Spiel abgenommen.

### Integrationsstand der Steam-Posenentwürfe

#36 entfernt abgelaufene Posen aus dem autoritativen Host-Zustand. #37 verbindet die Leon-Motion-Diagnose mit der Steam-Bridge. #38 bindet Rejoin-Snapshots an eine Anfragekennung. #39 und #40 führen diese Arbeiten zusammen; ein Linux-CI-Fehler in #40 zeigte, dass der Gast seine Kennung beim Warten über mehrere Peer-Timeouts behalten muss. #41 bindet Gast-Vorschläge an die geprüfte Host-Sitzung; #42 integriert dies in den kombinierten Zweig. Für #40 und #42 sind Python- und Lua-CI grün. #43 verbindet das Lobby-Modell aus #27 mit der Steam-Bridge: Host-Auswahl, Einstellungen und Bereitschaft werden in derselben Host-Sitzung ausgetauscht. Ein neuer Gast-Handshake verwirft die bisherige Bereitschaft auch ohne vorherigen Host-Timeout. 86 Python-Tests lokal sowie Python- und Lua-CI bestehen. Ein nativer Einzelinstanz-Test mit RE2 Build 11636119 bestätigte die echte Pipe, Host-Auswahl im Warten und die Ablehnung von Bereitschaft ohne Peer. Das temporäre Plugin wurde anschließend entfernt; alle zwölf erfassten Steam-Spielstanddateien blieben bytegleich. Slotkennung und Einstellungen sind bisher Metadaten; RE2-Laden und Kampagnenstart fehlen. Alle genannten PRs bleiben Entwürfe. Der Prozess-Test nutzt einen simulierten Link; zwei echte RE2-Instanzen und zwei Steam-Konten wurden damit noch nicht geprüft.

#44 ergänzt eine experimentelle ImGui-Lobby-Ansicht und leitet Host-Einladungsanforderungen an die native Steam-Pipe weiter. Die Stilfarben-Korrektur verwendet das native 32-Bit-Format; Regressionstest und CI bestehen. Frühere Fensteraufnahmen zeigten weder die Ansicht noch die Minimalprobe, und ein Nightly-Lauf hatte fortlaufende D3D12-Resets. Der spätere aktive Bildschirmtest auf dem aufbauenden Zweig #45 bestätigt nun Rechteck, Text, ImGui-Fenster und vollständige Host-Lobby am Titelbild in 1920x1080. Verwendet wurden die ursprüngliche Dinput8-Verknüpfung und unveränderte D3D12-Grafikwerte. Beide Läufe hatten je zwei ImGui-Initialisierungen und fünf Resize-Buffer-Aufrufe. Die Ursache der früheren Reset-Schleife ist nicht bewiesen; die sichtbare Host-Ausgabe ist unter den geprüften Bedingungen nachgewiesen. [LOBBY_MENU.md auf #45](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-native-save-catalog/LOBBY_MENU.md) enthält Ablauf und Grenzen.

#45 bindet die Host-Auswahl optional an den nativen Szenario-Spielstandkatalog. Der Exporter liest die vorhandene SaveDataManager-Tabelle ohne Lade-, Speicher-, Lösch- oder Setter-Aufruf. Der Host prüft Slot, Szenario, Zeitwert, Metadaten-Digest und Frische; ein optionaler Datumsfilter begrenzt die Auswahl. Referenzänderung oder Quellenverlust setzen beide Bereitschaftswerte über eine neue Lobby-Revision zurück. 93 Python-Tests und die aktualisierten Lua-Suiten bestehen lokal; auch die Python- und Lua-CI auf PR #45 ist grün. Ein nativer Einzelinstanz-Test am Titelbild las neun Einträge, ließ mit dem Filter 2026-11-11 genau Slot 4 zu und wies eine direkt eingeschleuste neuere Auswahl ab. Alle zwölf erfassten Steam-Spielstanddateien blieben unverändert. In der sichtbaren Host-Lobby wurde der erlaubte Eintrag mit terminalgesteuerter Maus ausgewählt und übernommen. Der Bereit-Knopf blieb ohne Gast gesperrt. Der Einladungsbutton öffnete den echten Steam-Dialog, der ohne Kontaktwahl geschlossen wurde. hide/show sowie die Eingabesperre nach Ende der Bridge wurden nativ geprüft. Der neue Aufnahmehelfer erfasst nur das aktive RE2-Fenster ohne Fokus- oder Grafikänderung. Die grundlegende Host-Bedienung ist damit für 1920x1080 bestätigt. Auf diesem Zweig benötigen die Eingaben noch das REFramework-Debug-Menü; #46 ergänzt den eigenständigen Pfad. Andere Auflösungen, Gastansicht, Laden und gemeinsames Speichern bleiben offen. Nach beiden Tests wurden die Originalordner und Einstellungen wiederhergestellt; alle zwölf erfassten Speicherdateien blieben unverändert. Der Entwurf baut auf #44 auf. Der Digest umfasst Metadaten, nicht den Inhalt der Speicherdatei. [SAVE_CATALOG.md auf dem Entwurfszweig](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-native-save-catalog/SAVE_CATALOG.md) beschreibt Bedienung und Grenzen.

#46 ergänzt eine eigene Eingabesteuerung ohne geöffnetes REFramework-Debug-Menü. F9 schließt und öffnet die Lobby. Der Mod erneuert die native Inhibit-Maske pro Input-Update und entfernt beim Freigeben nur seine eigenen Cursor-/Mausanforderungen. Die Freigabe wartet auf zwei neutrale Updates einschließlich unabhängiger Fensterereignisse. Ein nativer Fehler beim Halten einer Maustaste wurde damit behoben und durch einen Regressionstest erfasst, der vor der Korrektur scheitert. Im Einzelinstanz-Test wurde der erlaubte Spielstand im sichtbaren Dropdown übernommen. Bei F9 mit gehaltener Maustaste oder W blieb die Sperre bis zum Loslassen aktiv. Ein Klick auf Spiel starten unter der Lobby blieb wirkungslos und öffnete nach dem Schließen das Hauptmenü. Der Nachweis gilt für Maus/Tastatur am Titelbild in 1920x1080; keine Kampagne wurde geladen. Python- und alle Lua-CI-Suiten auf #46 sind grün. Die Originaldateien sind zurückgestellt, alle zwölf erfassten Speicherdateien blieben unverändert. Physische Controller, Fokuswechsel und Kampagneneingaben sind noch offen. [LOBBY_INPUT.md auf dem Entwurfszweig](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-lobby-input/LOBBY_INPUT.md) beschreibt Installation und Prüfumfang.

#47 ergänzt eine ausdrücklich aktivierte native Speicher-/Ladeprobe auf Basis von #46. Der Loader wartet nach der konkreten Slotanforderung auf das abgeschlossene asynchrone Dateilesen, bevor er den Szenenwechsel startet. Originalmenü und korrigierte Probe erreichten ausschließlich den freigegebenen alten Slot. Beim direkten Laden vom ersten Titelbild blieb jedoch das Titel-Overlay über der steuerbaren Welt sichtbar. `scene_loaded` bestätigt deshalb nur Szene und Spielerobjekt; ein nutzbarer Kampagnenstart und die gemeinsame Ladebarriere fehlen. Nach gesonderter ausdrücklicher Freigabe wurde genau eine Speicheranforderung an den gesicherten alten Slot gesendet: Der installierte Guard zählte einen abgefangenen Aufruf, die API gab `false` zurück und der Save-Manager blieb inaktiv. Alle zwölf erfassten Speicherdateien blieben unverändert; Originalordner und Einstellungen sind wiederhergestellt. Das belegt diesen Einstiegspunkt, nicht jeden Engine-Schreibpfad. 97 Python-Tests und acht Lua-Suiten bestehen lokal; die CI auf dem aktuellen PR-Kopf ist ebenfalls grün. Ein weiterer Kampagnentest bestätigt den begrenzten Bewegungsvergleich der Lobby: S für 200 ms ergab bei Erfassung 0 m über 37 frische Proben, nach F9 rund 0,073 m über 22 Proben. Zielen, Schießen, Cutscenes, Controller und Fokuswechsel bleiben offen. [READONLY_LOAD.md auf dem Entwurfszweig](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-readonly-save-load/READONLY_LOAD.md) beschreibt Aktivierung, Nachweise und den offenen Menüabschluss.

#48 von bySenom ergänzt einen lesenden Steam-Test-Preflight für Prozess, lokale Plugin-/Skriptdateien, Lobbyrolle, bestätigten Roundtrip und frische Spielerpose. Seine CI ist grün. Der dokumentierte Sololauf bestätigt erwartete Negativbefunde ohne Gast beziehungsweise Kampagne; er ersetzt keinen positiven Zwei-Instanzen-Nachweis. Der einzelne Beitrag `e10e935` wurde im Entwurf #51 isoliert auf #50 übernommen und gemeinsam geprüft. Sein gesamter Zweig weicht vom kombinierten Steam-Stand ab und darf nicht ungeprüft als Gesamtstand übernommen werden.

#49 von bySenom ergänzt eine passive Titel-/Menü-Ablaufspur. Der Commit baut nachweislich direkt auf #47 auf; die PR-Basis wurde deshalb von `main` auf den tatsächlichen #47-Zweig ausgerichtet. Der Diff umfasst nur das Diagnoseskript und seine Dokumentation. Die erweiterte Spur in #51 deckt 17 Ziele einschließlich der für #50 bestätigten GUIMaster-Abschlüsse und des Titelflow-Zustandsetters ab. Ein-/Austrittsereignisse sind begrenzt; diagnostische Spiel-Getter laufen außerhalb der nativen Hooks. Im frischen nativen Titelbild-Lauf wurden die Installation und sieben tatsächlich durchlaufene Hookziele protokolliert. Der Originalmenü-/Kampagnenmenü-Vergleich und der offene Fehlerpfad bleiben ungeprüft.

#50 ergänzt den gezielten Abschluss der jeweils geöffneten Titel-/Haupt-/Kampagnenmenüs über deren native GUIMaster-Methoden, wartet auf geschlossene Menüstatuswerte und übergibt anschließend über den bestätigten FINALIZE-Zustand an den nativen Titelflow. Ein Einzelinstanz-Test vom ersten Titelbild zeigt den alten Spielstand ohne Titel-Overlay, mit erhaltener Interaktionsanzeige. Ein reiner FINALIZE-Zwischenstand ließ im Kampagnenmenü noch dessen Hilfszeile zurück; die endgültige Wiederholungsprüfung ist nicht bestanden: Nach einer abgefangenen Fortsetzen-Abkürzung und der originalen Fehlermeldung stürzte eine anschließende konkrete alte-Slot-Lesung mit `0xc0000005` in `re2.exe` ab, bevor der neue Menüabschluss lief. Die Ursache ist offen. CLI und Loader verweigern vorläufig weitere kontrollierte Anforderungen nach einer abgefangenen nativen Ladeanforderung; das ist kein Nachweis einer Absturzbehebung. Alle zwölf erfassten Speicherdateien blieben unverändert, die Originalinstallation ist wiederhergestellt. 98 Python-Tests und neun Lua-Suiten bestehen lokal und die CI auf #50 ist grün. Die Probe bleibt ein Entwurf; gemeinsame Ladebarriere, Speichern und Zwei-Instanzen-Abnahme fehlen.

#51 führt die abgegrenzten Beiträge von bySenom aus #48 (`e10e935`) und #49 (`e1b3cca`) auf #50 zusammen. Die Originaldateien wurden zunächst per Git-Blob-Hash verglichen; der ältere Gesamtzweig von #48 wurde nicht übernommen. Der Preflight behandelt auch nicht lesbare Dateimetadaten. Sowohl die 17-Ziel-Titelspur als auch die sieben Hooks der vorhandenen JSON-Ladeprobe verwenden nun begrenzte Ein-/Austritte mit ausdrücklich älteren `cached`-Statuswerten. Diagnosefehler verändern weder Originalaufrufentscheidung noch Rückgabewert. 104 Python-Tests und zehn Lua-Suiten bestehen lokal; die CI des aktuellen Kopfes ist grün. Der lesende CLI-Negativtest bei geschlossenem RE2 bleibt bestätigt. Ein ergänzender frischer RE2-Hintergrundlauf lud ausschließlich den freigegebenen alten Slot vom Titelbild bis `scene_loaded`: genau eine erlaubte Anforderung, keine abgefangene Ladeanforderung und kein erfasster Speicheraufruf. Die native Spur erfasste Titelabschluss, FINALIZE, Szenenwechsel, Titelentladen und den fertigen Ladestatus. Ohne aktive Bildschirmaufnahme oder Menüeingabe ist das kein neuer visueller oder Kampagnenmenü-Nachweis. Nach bestätigtem Prozessende wurden die Originaldateien zurückgestellt; alle zwölf Speicherdateien blieben bytegleich, keine neue erschien. Absturzursache, Kampagnenmenü-Wiederholung, positive Zwei-Rechner-Abnahme und gemeinsame Ladebarriere bleiben offen. #51 ist ein ungemergter Entwurf. [INTEGRATION_LOAD_TOOLS.md](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-load-tools-integration/INTEGRATION_LOAD_TOOLS.md) hält Herkunft, Grenzen und das nächste native Vorgehen fest.

#52 von bySenom (`7e54fc3`, direkt auf #51) schützt die aktive Slotfreigabe gegen weitere Lade- und Arm-Befehle während Dateilesung, Menüabschluss und Szenenwechsel. Die Diagnose trennt letzte Befehls-ID, aktive Policy-ID und native Lade-ID. #53 (`f350f59`, auf #52) ergänzt `readonly_save_control.py --wait`, das nur die eigene Freigabe beziehungsweise den eigenen nativen Abschluss bestätigt. Ein Timeout verändert keine laufende Anforderung. Ihre tatsächlichen PR-Basen sind jetzt #51 beziehungsweise #52, sodass nur die abgegrenzten Änderungen im Diff stehen.

#55 von bySenom (`dec7f62`, direkt auf #51) verlangt passende lokale Gast-Metadaten vor nativer Bereitschaft und sendet dafür einen Identitätsdigest aus Modus, Slot, Zeitwert und Szenario. Quellenverlust nimmt die Gastbereitschaft zurück; Anzeigetexte dürfen lokalisiert sein. Menü und Terminal zeigen den lokalen Abgleich. Der Zweig enthält inzwischen zusätzlich die Integration `1106aad` mit dem ursprünglichen #54-Stand; daraus wurden nur die ergänzende Feldwiederverwendung und der gemeinsame Rücknahmetest übernommen.

#54 bindet eine zusätzlich aktivierbare Dateivorprüfung an dieselbe Sitzung, Lobby-Revision und zufällige Versuch-ID. Beide Seiten lesen die ausgewählte native Datei ausschließlich lokal, vergleichen SHA-256 und bestätigen mit steigender Sequenz; nur neue Bestätigungen verlängern die fünfsekündige Frist auf der monotonen Host-Uhr. Änderungen, Quellenverlust, Abbruch, Wiederbeitritt und Fristablauf invalidieren den Versuch. `prepared` bestätigt gleiche Dateibytes, keinen nativen Ladevorgang oder gleichen Weltzustand. Die Einzelbeiträge aus #52/#53/#55 sind auf #54 zusammengeführt; 13 unverändert übernommene Dateien wurden per Git-Blob-Hash mit den Originalbeiträgen verglichen. 123 Python-Tests und zehn Lua-Suiten bestehen im kombinierten Stand; die CI ist grün. Ein lokaler nativer Katalog-/Dateitest las nur die freigegebene Datei vom 11.11.2026, bestätigte wiederholt ihren Sicherungshash und wies die neuere Auswahl ab. Dabei gab es keine Kampagnenladeanforderung; nach dessen Prozessende wurden die Originaldateien und zwölf unveränderte Speicherdateien bestätigt. Ein frischer Titelbild-Lauf bestätigte anschließend `--load --wait` für die eigene native Lade-ID. Ein zweiter, vorab datumsgeprüfter Arm-Befehl für denselben alten Slot wurde während `closing_menu` im lokalen Postfach mit `load_in_progress` abgewiesen, ohne die ursprüngliche Policy- oder Lade-ID zu ersetzen. Die erste Anforderung erreichte `scene_loaded`; eine spätere Arm-Bestätigung erhielt ihre neue Policy, während das vorherige Ladeergebnis erhalten blieb. Es blieb bei genau einer nativen Leseanforderung und keinem erfassten Speicheraufruf. Nach Prozessende wurden Originaldateien und zwölf unveränderte Speicherdateien bestätigt. Das belegt diesen Titelbild-/Überlappungspfad; andere Phasen, Kampagnenmenü, Fehlerpfad und Gast-Menüanzeige bleiben offen. Die Gast-Menüprüfung und alle Zwei-Instanzen-Anforderungen bleiben offen. [SHARED_LOAD.md](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-shared-load-preflight/SHARED_LOAD.md) hält Herkunft, Bedienung und die verbleibende native Ladebarriere fest. Keine PR wurde durch diese Integration gemergt.

#56 von bySenom (`8536fea`, auf dem kombinierten #54-Stand) begrenzt den verifizierten Gast-Lobbyzustand auf drei Sekunden seiner eigenen monotonen Uhr. Fehlende Lobbyframes verwerfen Anzeige, Befehle, Bereitschaft und Bestätigungen, auch wenn Posen und Heartbeats weiterlaufen. Eine langsame Dateiprüfung kann nach Ablauf keine Bestätigung mehr senden. Der einzelne Beitrag ist in #58 übernommen; drei unveränderte Quell-/Testdateien stimmen per Git-Blob-Hash mit dem Original überein. Die PR-Basis ist auf #54 ausgerichtet; der Test mit zwei echten Steam-Instanzen bleibt offen.

#57 von bySenom baut nach geprüfter Commit-Kette auf #54 (`33556b7`) auf. Die PR-Basis wurde auf diesen Entwicklungszweig ausgerichtet; der Diff enthält fünf abgegrenzte Dateien. Der Beitrag fügt einen nativen Multiplayer-Menüeintrag hinzu und behandelt lokalisierte Originalzeilen sowie die Eingabefreigabe bei Rückkehr aus der Lobby. Der Autor berichtet einen eigenen nativen Mausklick-/Rückgabetest und 23 unveränderte Speicherdateien seiner Installation. Das ist kein Test auf dieser Installation mit zwölf Dateien. Tastatur/Controller, Auswahl einer Originaloption nach Rückkehr und die Kombination mit dem aktuellen Lade-/Zustandsstand bleiben offen. #57 wurde nicht in #58 übernommen und nicht gemergt.

#58 ergänzt einen ausdrücklich aktivierten lesenden Beobachter für `load_header_and_inventory_core`: nativer Ladekopf mit GUIDs/geladenen Kennungen sowie laufende Slot-Grundwerte, reservierte/breite Slots und Haupt-/Neben-/persönliche Ausrüstung. Zwei unmittelbar aufeinanderfolgende Abfragen müssen Daten und lokale Spieler-/Inventarobjekte bestätigen. Der Python-Leser bindet frische Samples an die eigene native Lade-ID und aktive Policy, passenden Slot/Szenario und eine begrenzte Anforderungsdauer. Sein Digest gilt nur für diesen Umfang, nicht für die vollständige Welt. Die native Untersuchung fand 32 temporäre SaveDataBase-Blöcke; deren logische Liste ist nach dem Laden leer. Der beobachtete native GameSaveDataHash blieb unverändert und wird nicht als Weltdigest verwendet. Ein frischer lokaler Lauf bestätigte fehlende Verfügbarkeit am Titelbild, danach den eigenen alten Ladevorgang, fünf steigende Samples mit gleichem Kerndigest und die Abweisung einer fremden Lade-ID. Genau eine native Leseanforderung, keine abgefangenen Lade-/Speicheraufrufe; nach Prozessende waren Originaldateien zurückgestellt und zwölf Speicherdateien bytegleich, keine neue erschien. 131 Python-Tests, elf Lua-Suiten und die CI des aktuellen Kopfes bestehen. Innere/zusätzliche Itemdaten, Shortcuts, Itembox, andere Inventare und sämtliche weiteren Welt-/Story-/Cutscene-Daten sowie Zustandsanwendung, Weltstillstand und Zwei-Instanzen-Abnahme fehlen weiterhin. [LOAD_WITNESS.md](https://github.com/Maaviis/re2-remake-coop/blob/codex/m1-native-load-witness/LOAD_WITNESS.md) dokumentiert Schnittstellen und Grenzen.

#59 baut als eigener Draft auf #58 (`561031c`) auf und erweitert den Leser um den getrennten Umfang `load_header_and_inventory_detail`: DefaultItem, AdditionalItem und ExData, Slot-Innen-/Zusatzdaten, letzter Waffentyp sowie die vier nach Richtung gebundenen Haupt-/Neben-Shortcuts. Der Kernumfang bleibt unverändert. Die Felder und lebenden Werte wurden in einer lesenden alten-Slot-Untersuchung bestätigt; dies ersetzt nicht die Abnahme des fertigen Readers. 136 Python-Tests und elf Lua-Suiten bestehen lokal; auch die [CI auf #59](https://github.com/Maaviis/re2-remake-coop/actions/runs/43737593538) ist grün. Zwei Abnahmeversuche des fertigen Readers meldeten zunächst erwartete Nichtverfügbarkeit am Titelbild und brachen dann beim Szenenladen mit `0xc0000005` im vom Framework genannten NVIDIA-Modul ab. Windows meldete zeitgleich erschöpften virtuellen Speicher (Ereignis 2004); auch ein unveränderter #58-Kernleser erreichte unter erneutem Speichermangel keinen Ladeabschluss, und ein PowerShell-Start scheiterte mit `OutOfMemoryException`. Die genaue Absturzursache bleibt offen. Nach jedem isolierten Lauf waren Originalskripte/-konfiguration zurückgestellt und alle zwölf Speicherdateien unverändert, keine neue erschien. Diese fehlgeschlagenen Versuche liefern keinen Nach-Laden-Nachweis; der spätere erfolgreiche Wiederholungslauf ist unten getrennt aufgeführt. Weitere Inventare, Itembox, Effektflags, native Anwendung und sämtliche Zwei-Instanzen-Nachweise fehlen weiterhin. Andere Anwendungen und globale Systemeinstellungen wurden nicht verändert. [INVENTORY_WITNESS.md](https://github.com/Maaviis/re2-remake-coop/blob/codex/m2-inventory-details/INVENTORY_WITNESS.md) enthält Umfang und Befunde. #57 bleibt separat; keine PR wurde gemergt.

#59 ist inzwischen auf demselben unveränderten Code nach Laden in einer frischen lokalen Instanz bestätigt: Bei wieder ausreichendem Systemspeicher meldete der Reader vor dem Laden erwartete Nichtverfügbarkeit und danach fünf frische Proben mit gleichem Detail-Digest. Erfasst wurden 20 logische Slots bei 12 nutzbaren Plätzen und je vier Haupt-/Neben-Shortcuts; 84.513 JSON-Bytes lagen innerhalb der Grenze. Eine fremde Lade-ID wurde abgewiesen. Genau eine erlaubte Leseanforderung, null abgefangene Ladeanforderungen und kein Speicheraufruf; nach Prozessende waren Originaldateien zurückgestellt und zwölf Save-Dateien unverändert, keine neue erschien. Es gab keinen Fokuswechsel oder Tastatur-/Mauseingaben. Die früheren Abbrüche sind historisch dokumentiert; ihre Ursache ist damit nicht behoben. Die Feld-/Detailabnahme in einer Instanz ersetzt weder Itembox/andere Inventare noch vollständigen Weltvergleich, Stillhalten, Anwendung oder Tests mit zwei echten Instanzen.

Der anschließende native Szenenzeitversuch bestätigt eine wichtige Grenze der Ladebarriere: `via.Scene.get_TimeScale`/`set_TimeScale(System.Single)` sind auf TDB 70 vorhanden. Bei `TimeScale=0.0` blieb der beobachtete Claire-Idle-Animationsframe über 50 frische Proben gleich, während `GameClock.get_SystemElapsedTime`, `get_GameElapsedTime`, `get_ActualPlayingTime`, `get_ActualRecordTime` und `get_InSceneTime` jeweils weiterliefen. In diesem Messfenster stiegen die fünf Rohzähler jeweils um 7.395.520 native Einheiten. Die zweisekündige lokale Testfreigabe wurde sechs Sekunden lang erneuert; nach ausbleibender Erneuerung wurde der ursprüngliche Faktor 1.0 automatisch zurückgestellt und rückgelesen. Eine erste Testfassung mit ungeeigneter Integer-Übergabe konnte die Rückstellung nicht bestätigen und wurde beendet; die korrigierte Fassung verwendet echte Lua-Gleitkommawerte und bewahrt den gelesenen Originalwert. Das ist eine begrenzte Einzelinstanz-Messung, kein Nachweis angehaltener KI, Physik, Skripte oder Cutscenes und keine Spielfreigabe. Originaldateien und zwölf unveränderte Save-Dateien wurden nach beiden Versuchen bestätigt. Der globale Weltstillstand bleibt offen; als Nächstes den vorhandenen nativen Pausenablauf einschließlich sauberer Rückkehr, Uhren und Cutscene-Verhalten prüfen, anschließend an Versuch und verifizierte Prozess-/Link-Epoche binden.

### Konkrete Arbeitsteilung der neuen Beiträge

| Beitrag / bestehender Verantwortlicher | Abgegrenzte Arbeit | Nächster Übergabenachweis |
|---|---|---|
| #48, bySenom | Lesender Steam-Test-Preflight; Einzelbeitrag ist in #51 integriert | Positiver Test des gemeinsamen Standes auf beiden echten Testrechnern |
| #49, bySenom | Passive Ablaufspur; auf #47 aufgebaut, in #51 erweitert und im Titelbild-Lauf beobachtet | Frischer Originalmenü-/Kampagnenmenü-Vergleich mit sichtbarem Abschluss |
| #50, Maaviis/Codex | Kontrollierter Ladeadapter, Menüeigentümer, Fehlerzustände und Abnahmegrenzen | Frische Sitzung aus dem Kampagnenmenü; Absturzpfad isolieren und native Fehlerbehandlung nachweisen |
| #51, Maaviis/Codex / Integration #1 | Abgegrenzte Beiträge, Diagnose ohne zusätzliche Getter in Hooks; 104 Python-/zehn Lua-Suiten und nativer Titelbild-Lauf | Kampagnenmenü-/Fehlerprüfung und Review; keine PR-Zusammenführung ohne gesonderte Anweisung |
| #52/#53, bySenom | Schutz aktiver Ladefreigaben und getrennte Terminal-/Ladeergebnisse; Titelbild/closing_menu in #54 nativ bestätigt | Weitere Überlappungsphasen, Kampagnenmenü und native Fehlerbehandlung |
| #55, bySenom | Lokaler Gastkatalog, Identitätsdigest, Bereitschaftsrücknahme und Menühinweis; mit #54 abgeglichen | Echter Gast mit eigenem Steam-Konto, native Menüanzeige und Quellenwechsel |
| #54, Maaviis/Codex / Integration #1 | Dateivorprüfung, begrenzte Bestätigungsfristen und Zusammenführung der Einzelbeiträge | An den Versuch gebundene native Ladeanforderungen, Stillhalten beider Welten und Zustandsvergleich vor Spielfreigabe |
| #56, bySenom | Gast-Lobbyfrist, Bereitschaftsrücknahme und Befehlsverfall; isoliert in #58 übernommen | Prüfung mit zwei echten Steam-Teilnehmern bei weiterlaufenden Posen und ausbleibenden Lobbyframes |
| #57, bySenom | Nativer Multiplayer-Menüeintrag und Rückgabe der Eingabe; eigener Prüfzweig | Kombinierter nativer Menü-/Ladeablauf, Tastatur/Controller und Originaloption nach Rückkehr |
| #58, Maaviis/Codex / Welt und Integration | Lesender nativer Ladekopf und Inventarkern; an eigene Lade-ID gebundene Teilnachweise | Fehlende Inventar-/Welt-/Skriptleser ergänzen; anschließend vollständiger Zustandsvergleich, Anwendung und gemeinsame Ladebarriere |
| #59, Maaviis/Codex / Welt und Inventar | Getrennter Detailreader für Item-Payloads und gerichtete Shortcuts, auf #58 | Nach-Laden-Abnahme einer Instanz bestätigt; Itembox, andere Inventare und Effektflags ergänzen, dann Anwendung und Zwei-Instanzen-Vergleich |
| Native Qualitätssicherung / #7 | Pro Spielinstallation genau einen aktiven Testführer und dessen gestartete Prozess-ID protokollieren | Keine gleichzeitig veränderten Testordner derselben Installation und keine fremde Spielinstanz beenden; Vergleich vor/nach jedem Lauf |

Ein zweiter PC mit eigenem Steam-Konto ist derzeit laut Nutzer nicht verfügbar. Deshalb bleibt die Zwei-Instanzen-Abnahme offen. Als Nächstes unabhängig davon: den neuen Absturzpfad und die native Fehlerbehandlung isolieren, den gezielten Menüabschluss aus #50 in einer frischen Kampagnenmenü-Sitzung mit der erweiterten passiven Spur aus #51 abnehmen. Die getrennte Integration von #48/#49 ist in #51 vorbereitet; #54 führt zusätzlich die abgegrenzten Beiträge aus #52/#53/#55 und die gemeinsame Dateivorprüfung zusammen. Dateigleichheit ersetzt keinen portablen, unter zwei Konten bestätigten Weltzustand. #58 ergänzt den nativ bestätigten Teilbeobachter für Ladekopf und Inventarkern sowie #56; die übrigen nativen Zustandsleser und die an Versuch und verifizierte Link-Epoche gebundene Ladebarriere bleiben erforderlich. #59 ist nach der Ressourcenentspannung für den begrenzten Detailumfang in einer nativen Instanz bestätigt. Als Nächstes den nativen Pausenablauf für die gemeinsame Ladebarriere einschließlich Uhr-/Animationswerten und Rückkehr prüfen, weitere Inventar-/Weltleser ergänzen und Prozess-/Linkbindung vorbereiten. Die sichtbare Menüabnahme wartet zusätzlich auf einen passenden Vordergrundtermin. Der Menübeitrag #57 bleibt ein eigener zu integrierender Prüfzweig. Die Eingabesteuerung bei Fokuswechsel, Zielen und Schießen sowie die gestapelten Abhängigkeiten bleiben zu prüfen. Danach die bestätigte lokale Ladeanbindung an eine sitzungsgebundene Host-/Gast-Ladebarriere anbinden. Die grundlegende Host-Darstellung ist nativ bestätigt; die Ursache früherer Reset-Läufe bleibt ein gesonderter Diagnosepunkt. Für lokale Tests sind ausschließlich die ausdrücklich freigegebenen Spielstände vom 11.11.2026 zulässig; das Spiel wird nur über das Terminal gesteuert. Sobald der zweite Rechner verfügbar ist, die dokumentierten Zwei-Rechner-Tests aus STEAM_POSE_TEST.md und LOBBY_TEST.md für Einladung, beide Posenrichtungen, Motion, Ablauf, Host-Neustart sowie gleiche Auswahl und Bereitschaft ausführen. Ergebnisse pro Instanz protokollieren. Erst nach diesem Nachweis die Spieleraktions- und Kampfereignisse erweitern; die offenen Welt-, Kampagnen- und Speicherpakete bleiben eigenständige Aufgaben.

1. **Integration und Architektur (#1):** v1-Protokoll, Digest-Prüfung, Dauerevents und Handshake aus #8, #10, #12 und #13 in kleinen, nachvollziehbaren Schritten integrieren; danach die Observer- und Gastkette #9, #11, #14 bis #21 prüfen. Für jeden Schritt Schnittstelle, Tests und Abhängigkeit festhalten.
2. **RE2-Spieler und Kampf (#2):** #21 mit zwei echten RE2-Instanzen im selben Raum testen: getrennte Datenordner, beide Bewegungsrichtungen, Rotation, Sichtbarkeit, Abwesenheit und Wiederbeitritt. Die in #25 angelegte Kette mit zwei echten Spielinstanzen prüfen. Für #26 echte Leon-Sendedaten und die Darstellung im zweiten Spielprozess testen. Die in #37/#42 kombinierte Phasenabbildung und Terminalsteuerung nativ messen und nur bei passender Clip-Zuordnung übernehmen; danach die kontrollierte Zuordnung von Spieleraktion zu Clip, Übertragung über die v1-Sitzung und Wiedergabe auf dem Gastobjekt erweitern. Diese Integration braucht danach den Zwei-Instanzen-Nachweis; anschließend Gegner-IDs, Treffer, Schaden und Tod.
3. **Qualitätssicherung (#7):** Einzelinstanz-Nachweis, Prozesssimulation und Zwei-Instanzen-Nachweis getrennt protokollieren. Build, TDB, Sequenzen und beobachtete Abweichungen erfassen; keine lokalen Pfade, Kontodaten oder Speicherdateien veröffentlichen.
4. **Steam-Lobby (#5) und Speichern (#6):** die Verbindung aus #43 zwischen Host-/Revisionsmodell und Steam-Bridge mit zwei echten Konten abnehmen. Einladung, `ping` und v1-Posenübertragung mit zwei echten Steam-Konten prüfen, einschließlich Uhrversatz und Paketverzögerung aus #34 sowie Host-Bridge-Neustart und sitzungsgebundene Vorschläge aus #40/#42; die Ladeprobe aus #50 nach geprüfter Fehlerbehandlung und Menüvarianten als Grundlage für die gemeinsame Ladebarriere verwenden. Die Host-Ansicht aus #44/#45 und die eigenständige Titelbild-Eingabe aus #46 sind in 1920x1080 bestätigt; Ein begrenzter Kampagnen-Bewegungsvergleich ist auf #47 bestätigt; Fokuswechsel, Zielen/Schießen, physische Controller, Skalierung und Gastansicht bleiben vor der Menüfreigabe zu prüfen. Für lokale Spieltests nur die ausdrücklich freigegebenen Speicherstände vom 11.11.2026 verwenden und das Spiel ausschließlich über das Terminal steuern.
5. **Welt (#3) und Kampagne (#4):** stabile Objekt-IDs, Inventar und Rätsel sowie Skripte und jede Zwischensequenz mit eigenen Zwei-Instanzen-Tests anbinden. Diese Pakete bleiben offen.

## Arbeitspakete und Zuständigkeiten

Die Rollen bezeichnen Verantwortungsbereiche. Namen werden erst eingetragen, wenn Mitwirkende sie übernehmen. Jede Rolle besitzt ihren Ordner und liefert dokumentierte Schnittstellen, Beispielnachrichten und einen reproduzierbaren Test.

| Rolle | Verzeichnis | Aufgabe | Übergabe an Integration |
|---|---|---|---|
| Integration und Architektur | `protocol/`, Projektkonfiguration | Gemeinsames Nachrichtenschema, Sitzungskennung, Sequenz, Zustandsprüfung, Versionsabgleich, Review und Release | Versioniertes Schema und Kompatibilitätstest für jedes Paket |
| RE2-Spieler und Kampf | `game/player/`, `game/combat/` | REFramework-Hooks für Position, Rotation, Aktionen, Schaden, Gegner-IDs, KI-Zustand und Tod; Ereignisse anwenden ohne Echo-Schleife | Zwei Spielinstanzen zeigen dieselben Spieler- und Kampfereignisse |
| Welt und Inventar | `game/world/` | Stabile IDs für Gegenstände, Türen, Rätsel, Inventar und Fortschrittsflags; Konflikte bei gleichzeitiger Interaktion behandeln | Snapshot und Ereignisstrom für jede Weltkategorie |
| Skripte und Zwischensequenzen | `game/story/` | Kampagnenereignisse und jede Cutscene kartieren; Start, Zeit, Skip und Ende koordinieren | Szenenmatrix mit Tests für beide Rollen |
| Lobby und Steam | `network/`, `ui/` | Steam-Freundeseinladung, Lobbybeitritt, Status, Bereitschaft, Originalmenü-Stil, Transport und Verbindungsfehler | Zwei Konten verbinden sich über Steam; Host startet erst bei kompatiblen Einstellungen |
| Speichern und Wiederherstellung | `save/` | Host-Spielstand, Slotwahl, atomare Checkpoints, Laden, Wiederverbindung und Abgleich nach Unterbrechung | Rejoin während Kampf, Rätsel und Cutscene ohne Zustandsabweichung |
| Qualitätssicherung | `tests/`, `docs/` | Zwei-Instanzen-Testplan, Messprotokolle, Kompatibilitätsmatrix, Regressionen und Einschränkungen | Nachweis für jede Zeile in [STATUS.md](STATUS.md) |

## Gemeinsame Schnittstelle

Ein Spielmodul meldet ein typisiertes Ereignis mit stabiler Objekt-ID und lokaler Beobachtungszeit an den Host. Nur der Host vergibt Sitzungskennung, Sequenz und verbindlichen Zustand. Clients wenden Ereignisse in dieser Reihenfolge an und prüfen den Zustandswert. Bei Lücke oder Abweichung fordern sie einen Snapshot an. Gameplay-Module dürfen keine eigenen Netzwerkformate oder separaten Spielstände definieren. Das Schema wird vor den Engine-Hooks versioniert; inkompatible Versionen dürfen nicht gemeinsam starten.

## Reihenfolge der Integration

1. **M0 – Reproduzierbare Basis:** Unterstützten RE2-Build und REFramework-Version festlegen, Probe im Spiel validieren, CI für Protokolltests aufsetzen.
2. **M1 – Zwei Spieler:** Eigenständige Engine-Bridge und Steam-Lobby. Bewegung, Rotation und Aktionen in beiden Instanzen sichtbar.
3. **M2 – Gemeinsame Welt:** Gegner, Schaden, Tod, Gegenstände, Inventar, Türen und Rätsel einschließlich gleichzeitiger Interaktion.
4. **M3 – Kampagne:** Fortschrittsflags, Skriptereignisse und alle Cutscenes mit Szenenmatrix.
5. **M4 – Fortsetzen:** Host-Spielstand, Slotwahl, Unterbrechung und Wiederverbindung in kritischen Szenen.
6. **M5 – Freigabe:** Vollständiger Zwei-Instanzen-Durchlauf, dokumentierte Einschränkungen, Installations- und Bedienanleitung.

Ein Meilenstein gilt erst mit einem Test in zwei echten RE2-Instanzen als abgeschlossen. Python-Protokolltests sind nur Vorprüfungen.

## Zusammenführung

- Ein Branch pro Aufgabe, Pull Request gegen `main`, Review durch Integration und mindestens eine betroffene Fachrolle.
- Änderungen am Nachrichtenschema zuerst als eigener Pull Request mit Migration und Testvektoren; Gameplay-Module bauen auf der freigegebenen Version auf.
- Jeder Pull Request nennt RE2-Build, REFramework-Version, getestete Rollen, Messwerte und bekannte Lücken. Ungetestete Engine-Funktionen bleiben ausdrücklich experimentell.
- Fremdmod-Dateien, Spiel-Assets, Steam-Binärdateien, persönliche Logs und Speicherstände dürfen nicht ins Repository.
- Bei Konflikten gilt: Host-Zustand und dokumentiertes Schema vor lokalen Beobachtungen; reproduzierbare Fehler werden als Issue mit Logauszug und Schritten erfasst.
