# Steam-Lobby im laufenden RE2 prüfen

Das Windows-x64-Plugin verwendet den Steam-Kontext eines regulär über Steam gestarteten RE2. Es verwendet die bereits geladene `steam_api64.dll` und REFrameworks `UpdateBehavior` zum Ausführen der Befehle. Es öffnet eine private Lobby mit zwei Plätzen über die App-ID 883710.

Für die Probe eine Solo-Sitzung verwenden, in der keine andere Spiel- oder Mod-Lobby aktiv ist. Steam erlaubt pro Nutzer nur eine reguläre Lobby. Das Plugin erscheint im REFramework PluginLoader und bleibt inaktiv, bis ein Terminalbefehl eingeht.

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

Bei mehreren RE2-Prozessen den Zielprozess mit `-GameProcessId` auswählen. Die lokale Windows-Pipe akzeptiert die vier Befehle ausschließlich vom Windows-Benutzer des Spiels. Eine Antwort mit `accepted` bestätigt den Eingang. Die folgenden Zustände und das REFramework-Log zeigen den Ausgang:

- Nach `create` erst `creating` und nach dem Steam-Ergebnis `owned`. Im Log stehen App-ID, Eigentümerschaft, Mitgliederzahl und Kapazität.
- Bei `invite-dialog` öffnet Steam den Dialog. Der Befehl wählt keinen Kontakt aus. Das Schließen des Overlays erfolgt in Steam.
- `leave` verwirft auch eine noch ausstehende Lobby-Erstellung. Nach einem `LeaveLobby`-Aufruf zeigt `idle`, dass das Plugin keine Lobby mehr verwaltet. Die Benachrichtigung eines anderen Mitglieds lässt sich mit einem zweiten Konto prüfen.

Den Test mit `leave` beenden. Die DLL kann nach dem Beenden des Spiels wieder aus `reframework/plugins` entfernt werden.

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

## Beobachteter Stand

In RE2 Steam-Build 11636119 mit REFramework d1461375 legte die Terminal-Probe eine private Lobby mit zwei Plätzen an. Steam meldete den lokalen Nutzer als Eigentümer und einziges Mitglied. Im ersten Terminal-Lauf meldete das Steam-Renderer-Log das Anzeigen des Overlays unmittelbar nach dem Dialogaufruf. In der finalen Fassung wurde zweimal im selben RE2-Prozess eine Lobby erfolgreich erstellt und `LeaveLobby` vor dem nächsten Durchlauf aufgerufen. Die Probe verwirft auch ungültige und überlange Pipe-Anfragen. Ein isolierter negativer Gasttest startete denselben Build über Steam mit
einer synthetischen Lobby-ID. Die Probe erkannte den Startparameter und
`join-invite` führte zu Steams Antwort 2 für die fehlende Lobby. Der
Zustand ging auf `idle` zurück. Danach wurden im selben Prozess eine private
Host-Lobby erstellt und wieder verlassen. Die Callback-Registrierung im
laufenden Spiel wurde beobachtet. Die Zustellung einer echten Einladung,
der erfolgreiche Gastbeitritt und der Datentransport stehen aus.

[Steamworks Matchmaking](https://partner.steamgames.com/doc/api/ISteamMatchmaking) · [Steam-Einladungsdialog](https://partner.steamgames.com/doc/api/ISteamFriends#ActivateGameOverlayInviteDialog)
