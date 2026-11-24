# Steam-Lobby im laufenden RE2 prüfen

Das Windows-x64-Plugin verwendet den Steam-Kontext eines regulär über Steam gestarteten RE2. Es verwendet die bereits geladene `steam_api64.dll` und REFrameworks `UpdateBehavior` zum Ausführen der Befehle. Es öffnet eine private Lobby mit zwei Plätzen über die App-ID 883710.

Für die Probe eine Solo-Sitzung verwenden, in der keine andere Spiel- oder Mod-Lobby aktiv ist. Steam erlaubt pro Nutzer nur eine reguläre Lobby. Das Plugin erscheint im REFramework PluginLoader und bleibt inaktiv, bis ein Terminalbefehl eingeht.

Beim Wechsel in ein anderes Fenster oder beim Minimieren versorgt ein Timer
des Spielfensters die Lobby-Statusabfragen und den Posenkanal, sobald die
regulären Engine-Updates ausbleiben. Über diesen Kanal laufen auch die
Heartbeats zwischen Host und Gast. Bei der Rückkehr übernimmt wieder
`UpdateBehavior`. Die Steam-Mitgliedschaft und die bestehenden Fristen für
ausbleibende Peer-Antworten gelten während des Fokuswechsels weiter.
Der Timer benötigt eine laufende Windows-Nachrichtenschleife.

## Bauen

Benötigt werden CMake, ein Windows-x64-C++-Toolchain und zwei externe Header-Verzeichnisse:

- `include` aus REFramework [d1461375](https://github.com/praydog/REFramework/tree/d1461375)
- Ein Verzeichnis mit `steam/steam_api_flat.h`. Der Test nutzte `src/public` aus Valves [Source SDK e1f1fd4](https://github.com/ValveSoftware/source-sdk-2013/tree/e1f1fd42271805072f052051c26c21caa2c87b04/src/public).

~~~powershell
cmake -S network/steam_lobby_probe -B build/steam-lobby -A x64 `
  -DREFRAMEWORK_INCLUDE_DIR="C:/SDK/REFramework/include" `
  -DSTEAMWORKS_INCLUDE_DIR="C:/SDK/source-sdk-2013/src/public"
cmake --build build/steam-lobby --config Release
~~~

Bei beendetem RE2 die erzeugte `re2_coop_steam_lobby_probe.dll` nach `reframework/plugins` der Testinstallation kopieren. RE2 über Steam bis zum Hauptmenü starten. Für den Einladungsdialog muss das Steam-Overlay verfügbar sein.

## PowerShell-Befehle

~~~powershell
.\network\steam_lobby_probe\lobby.ps1 -Command status
.\network\steam_lobby_probe\lobby.ps1 -Command create
.\network\steam_lobby_probe\lobby.ps1 -Command status
.\network\steam_lobby_probe\lobby.ps1 -Command invite-dialog
.\network\steam_lobby_probe\lobby.ps1 -Command leave
~~~

Bei mehreren RE2-Prozessen den Zielprozess mit `-GameProcessId` auswählen. Die lokale Windows-Pipe akzeptiert die dokumentierten Befehle ausschließlich vom Windows-Benutzer des Spiels. Für `create` und `leave` bestätigt `accepted` den Eingang.

- Nach `create` erst `creating` und nach dem Steam-Ergebnis `owned`. Im Log stehen App-ID, Eigentümerschaft, Mitgliederzahl und Kapazität.
- `accepted invite-dialog` bestätigt den Steam-Aufruf zum Öffnen des Dialogs. Für die Einladung wählt der Host anschließend einen Kontakt im Steam-Overlay. Fehlen eine eigene Lobby oder ein verfügbares Overlay, antwortet das Plugin mit `error` und dem Grund.
- `leave` verwirft auch eine noch ausstehende Lobby-Erstellung. Nach einem `LeaveLobby`-Aufruf zeigt `idle`, dass das Plugin keine Lobby mehr verwaltet. Die Benachrichtigung eines anderen Mitglieds lässt sich mit einem zweiten Konto prüfen.

Den Test mit `leave` beenden. Die DLL kann nach dem Beenden des Spiels wieder aus `reframework/plugins` entfernt werden.

`lobby.ps1 -Command cloud-status` fragt mit dem Steam-Kontext des laufenden
RE2 die Steam-Cloud-Einstellungen ab. `cloud-enabled` meldet eine aktive
Synchronisierungseinstellung. `cloud-account-disabled` und
`cloud-app-disabled` geben an, auf welcher Ebene Steam Cloud ausgeschaltet
ist. `cloud-unavailable` bedeutet, dass die Abfrage keine Bestätigung
liefern konnte. Die Abfrage liefert ausschließlich den Status.

Die lokale Menü-Bridge fragt bei `invite-pending` zusätzlich
`invite-revision` ab. Die Antwort ist `none` oder eine dezimale
Angebotsrevision. `join-invite <Revision>` gilt nur für das gerade
beobachtete Angebot. Das Plugin prüft die Revision bei der Annahme des
Befehls und erneut vor dem Steam-Aufruf. Der Terminalbefehl
`lobby.ps1 -Command join-invite` bleibt für die direkte Diagnose verfügbar.
Die Gast-Bridge fragt bei einem fehlgeschlagenen Versuch
`join-error <Revision>` ab. Eine passende Ablehnung liefert `join-failed`
mit dem Grund. Andere Revisionen liefern `none`.

`membership-revision` liefert die dezimale Revision einer bestätigten
Mitgliedschaft oder `none`. `leave <Revision>` wird nur für die noch
aktive Mitgliedschaft angenommen. Die Revision wechselt bei jedem neuen
Beitritt oder Erstellen einer Lobby. Der direkte Diagnosebefehl
`lobby.ps1 -Command leave` bleibt für laufende lokale Tests verfügbar.

## Einladungsannahme mit zwei Konten prüfen

1. Dieselbe Plugin-Fassung in beiden Installationen verwenden. Der Host ruft
   `create` auf und wartet auf `owned`. Danach öffnet er `invite-dialog`
   und wählt das vereinbarte Testkonto.
2. Auf dem Gastkonto zunächst im laufenden RE2 die Einladung annehmen. Nach
   `invite-pending` im Terminal `join-invite` ausführen. Solange Steam oder
   die Lobby-Metadaten ausstehen, meldet das Plugin `joining` oder `verifying`.
   Erst nach erfolgreichem `LobbyEnter_t`, passender Koop-Kennung und der
   Prüfung der beiden Mitglieder folgt `joined`.
3. Den Versuch mit beendetem RE2 auf dem Gastkonto wiederholen. Beim Start
   übergibt Steam den Parameter `+connect_lobby`. Der Gast prüft wie zuvor
   `status` und führt `join-invite` aus.
4. Mit `leave` auf dem Gast und danach dem Host aufräumen. Wenn der Host die
   Lobby verlässt, beendet der Gast seine Mitgliedschaft beim nächsten Abgleich.
   Bei während des Beitritts ausgelöstem `leave` wird auch ein verspätetes
   erfolgreiches Steam-Ergebnis aufgeräumt.

Beim Beitritt aus dem Overlay gleicht die Probe den ursprünglichen
Lobby-Eigentümer mit der von Steam gelieferten Freund-ID ab, sofern sie
vorliegt. Der Startparameter liefert ausschließlich die Lobby-ID. Bei
Fragen zur Kompatibilität den Logstatus und den numerischen Steam-Fehler
festhalten. Die Lobby-Kennung beschreibt die Probe-Version. Sie stellt
keine Verbindung für Gameplay-Daten her.

Die lokale Prüfung des Startparameters lässt sich mit
`ctest --test-dir build/steam-lobby -C Release --output-on-failure`
wiederholen.

## Transport mit zwei Steam-Konten prüfen

Nach dem erfolgreichen Lobbybeitritt zeigt `peer-status` auf beiden Seiten
`peer-ready`, sobald Steam beide Mitglieder für die aktuelle Lobby meldet.
Auf jeder Seite nacheinander ausführen:

~~~powershell
.\network\steam_lobby_probe\lobby.ps1 -Command ping
.\network\steam_lobby_probe\lobby.ps1 -Command peer-status
~~~

`peer-round-trip-verified` bedeutet, dass ein passendes Pong mit einmaliger
Kennung aus derselben Lobby vom erwarteten Steam-Peer zurückkam. Bei fehlender
Antwort endet die Probe nach 15 Sekunden. Bei Austritt oder einem beobachteten
Mitgliederwechsel setzt die Probe den Status zurück. Nach Wiederbeitritt
eine neue Probe auslösen. Die Mitgliedschaft wird alle 100 ms abgefragt.
Ein schneller Austritt und Wiederbeitritt desselben Kontos zwischen zwei
Abfragen kann unerkannt bleiben. Die Probe schließt ihren Nachrichtenkanal
bei einem erkannten Wechsel. Steam verwaltet die zugrunde liegende Peer-Sitzung.

Die Windows-Buildtests prüfen Nachrichtenformat, Lobby-Zuordnung und
Antwortkorrelation. Der native Solotest bestätigte die Initialisierung von
Steam Networking Messages für RE2 Build 11636119 sowie die Ablehnung eines
Pings ohne zweites Lobby-Mitglied. Ein Ping über das Steam-Netz mit zwei
Konten und die Übertragung von Posen stehen aus.

Die lokale Pipe `re2-coop-steam-pose-<PID>` bedient Steam-Kanal
883. Die zusätzliche `re2-coop-steam-snapshot-<PID>` bedient Kanal
884 mit eigener Empfangsqueue und eigener lokaler Epoche. Beide nutzen
die dokumentierte Nachrichtenhülle, Größenbegrenzung und Peer-Prüfung.
Überlauf setzt nur die betroffene Queue zurück. Bei erkanntem Lobby-
oder Mitgliederwechsel schließt das Plugin beide Kanäle. Der
[gleichzeitige Pose- und Snapshottest](../../STEAM_POSE_TEST.md#posen-und-gegner-gleichzeitig-übertragen)
verwendet die zusätzliche Pipe auf beiden Rechnern.

[Steam Networking Messages](https://partner.steamgames.com/doc/api/ISteamNetworkingMessages)

## Beobachteter Stand

In RE2 Steam-Build 11636119 mit REFramework d1461375 legte die Terminal-Probe eine private Lobby mit zwei Plätzen an. Steam meldete den lokalen Nutzer als Eigentümer und einziges Mitglied. Im ersten Terminal-Lauf meldete das Steam-Renderer-Log das Anzeigen des Overlays unmittelbar nach dem Dialogaufruf. In der finalen Fassung wurde zweimal im selben RE2-Prozess eine Lobby erfolgreich erstellt und `LeaveLobby` vor dem nächsten Durchlauf aufgerufen. Die Probe verwirft auch ungültige und überlange Pipe-Anfragen. Ein isolierter negativer Gasttest startete denselben Build über Steam mit
einer synthetischen Lobby-ID. Die Probe erkannte den Startparameter und
`join-invite` führte zu Steams Antwort 2 für die fehlende Lobby. Der
Zustand ging auf `idle` zurück. Danach wurden im selben Prozess eine private
Host-Lobby erstellt und wieder verlassen. Die Callback-Registrierung im
laufenden Spiel wurde beobachtet. Die Zustellung einer echten Einladung,
der erfolgreiche Gastbeitritt und der Datentransport stehen aus.

Im Negativtest mit synthetischer Starteinladung bestätigte die laufende
Gast-Bridge zu Steams Antwort 2 den Fehler `Steam lobby no longer exists`.
Die Abfrage mit einer anderen Revision lieferte `none`.

Ein weiterer Terminaltest in RE2 prüfte `invite-dialog` vor und nach dem
Verlassen der Lobby. Das Plugin meldete jeweils die fehlende eigene Lobby.
Im Zustand `owned` protokollierte es den Steam-Aufruf. Der Lauf endete ohne
Kontaktauswahl.

[Steamworks Matchmaking](https://partner.steamgames.com/doc/api/ISteamMatchmaking) · [Steam-Einladungsdialog](https://partner.steamgames.com/doc/api/ISteamFriends#ActivateGameOverlayInviteDialog)
