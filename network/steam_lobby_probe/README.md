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

## Beobachteter Stand

In RE2 Steam-Build 11636119 mit REFramework d1461375 legte die Terminal-Probe eine private Lobby mit zwei Plätzen an. Steam meldete den lokalen Nutzer als Eigentümer und einziges Mitglied. Im ersten Terminal-Lauf meldete das Steam-Renderer-Log das Anzeigen des Overlays unmittelbar nach dem Dialogaufruf. In der finalen Fassung wurde zweimal im selben RE2-Prozess eine Lobby erfolgreich erstellt und `LeaveLobby` vor dem nächsten Durchlauf aufgerufen. Die Probe verwirft auch ungültige und überlange Pipe-Anfragen. Die Annahme einer Einladung, der Beitritt des Gasts, der Datentransport und das gemeinsame Spiel sind eigene Integrationsschritte.

[Steamworks Matchmaking](https://partner.steamgames.com/doc/api/ISteamMatchmaking) · [Steam-Einladungsdialog](https://partner.steamgames.com/doc/api/ISteamFriends#ActivateGameOverlayInviteDialog)
