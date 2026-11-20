# Asynchrone Steam-Lesezugriffe vor einer Speicherisolation prüfen

Die [Erweiterung zur Ziel-/Abschlusszuordnung](NATIVE_STORAGE_READ_TARGETS.md)
verwendet inzwischen Export-Schema 2 mit einem festen Katalog bekannter
API-Schlüssel und begrenzter Historie. Die folgende ursprüngliche Messung
und Beschreibung beziehen sich auf die Schema-1-Beobachtung ohne Dateiziele.

Ein vollständig spielbarer Koop-Test braucht einen verlässlichen gemeinsamen
Lade- und Speicherpfad. Die bisherigen Kampagnenproben halten persönliche
Save-Dateien gesperrt. Eine spätere isolierte Testumgebung darf daher nicht
auf der ungeprüften Annahme beruhen, dass RE2 ausschließlich synchron liest.

Der kontrollierte Versuch vom 18. November 2026 zeigt Leseaufrufe über
`ISteamRemoteStorage014.FileReadAsync` und `FileReadAsyncComplete` im
Ladezeitraum des freigegebenen alten Slots. Synchrones `FileRead` wurde in
diesem Lauf nicht aufgerufen. Eine Speicherumleitung ist damit noch nicht
implementiert oder freigegeben.

## Optionale Beobachtung neben der Schreibsperre

Das native Plugin `network/steam_save_guard` kann zusätzlich mit der
Prozessumgebungsvariable `RE2_COOP_STORAGE_READ_TRACE=1` gestartet werden.
Ohne diese ausdrückliche Option bleiben alle Leseeinträge unverändert und
es wird kein zusätzlicher Lesestatus veröffentlicht. Die installierte
Nutzerfassung wurde durch diesen Beitrag nicht ersetzt.

Die Option ergänzt Weiterleitungen für die Slots 1, 3 und 4 der offiziellen
[RemoteStorage014-Definition von Valve](https://github.com/ValveSoftware/Proton/blob/proton_9.0/lsteamclient/steamworks_sdk_151/isteamremotestorage.h).
Jede Weiterleitung erhöht einen atomaren Zähler und ruft genau einmal die
ursprüngliche Methode mit unveränderten Argumenten auf. Sie gibt deren
Ergebnis unverändert zurück. Es werden weder Dateinamen noch Inhalte,
Bufferadressen, API-Handles oder Kontokennungen kopiert oder exportiert.
Nur positive synchrone Rückgabewerte werden zusätzlich als
`sync_reported_bytes` summiert. Dieser Wert misst keine asynchron gelesenen
Bytes und ist kein Prüfsummen- oder Inhaltsnachweis.

Die zehn schreibenden Vtable-Einträge bleiben durch den vorhandenen Guard
gesperrt. Dessen Statusformat und Freigabebedingungen bleiben unverändert.
Die Beobachtung biegt keine flachen Steam-Exporte global um und führt
weder Lade-, Speicher- noch Cloud-Schreiboperationen aus.

Der zusätzliche `StorageReadObserver` verlangt eine gültige, lesbare
Tabelle und verändert ausschließlich die drei Leseeinträge. Er stellt den
ursprünglichen Seitenschutz wieder her und prüft die Ersatzzeiger. Pro
Prozesslebensdauer ist nur eine erfolgreiche Anbindung erlaubt. Die
ursprünglichen Weiterleitungsziele bleiben danach unveränderlich, damit
bereits eingetretene oder zwischengespeicherte Aufrufe auch nach einem
Detach keinen zerstörten Beobachter verwenden. Ein erneutes Anbinden oder
ein Laufzeit-Neuladen des Plugins wird nicht unterstützt. Beim Detach werden
nur noch selbst belegte Einträge zurückgestellt.

Außerhalb der Weiterleitungen schreibt das Plugin einmal pro Sekunde
`reframework/data/re2_coop_storage_reads.json` atomar. Schema 1 enthält
Quelle `steam_storage_reads`, Umfang `remote_storage_014_reads`, PID,
Startkennung, App/Build, Zeitpunkt, Verfügbarkeit/Grund, die drei Zähler
und die synchron gemeldete Bytemenge. Zählerfelder bilden keine gemeinsame
atomare Momentaufnahme über gleichzeitig laufende Aufrufe. Ein Verbraucher
muss die eigene PID/Startkennung, Integrität, Alter und Quellkontinuität
zusätzlich prüfen. Ein alter Status nach Prozessende ist keine Freigabe.

## Geschützter nativer Vergleich

Der private Treiber sicherte zuerst die unveränderte installierte Guard-DLL
und alle zwölf geschützten Save-/Cache-Dateien. Erst nach erworbenen
Dateisperren tauschte er ausschließlich diese DLL temporär und atomar gegen
den neu gebauten Beobachter aus. Die geerbten Dateihandles und die native
Schreibsperre waren beim eigenen direkten Spielstart aktiv. Die Strong-Guard-
und Leseberichte wurden an dieselbe PID und Startkennung gebunden.

Geladen wurde genau einmal Slot 4 vom 11.11.2026, Claire im Geheimraum,
auf RE2 Build 11636119 / REFramework d1461375 / TDB 70. Es gab keine
Bewegungs-, Kampf- oder Speicherbefehle. Der Treiber wartete auf unabhängige
frische native Gegnerberichte und drei sekundlich fortschreitende
Leseberichte nach dem Laden.

| Beobachtung | Vor dem Load | Nach dem Load |
|---|---:|---:|
| `FileRead` | 0 | 0 |
| `FileReadAsync` | 2 | 4 |
| `FileReadAsyncComplete` | 2 | 4 |
| Synchron gemeldete Bytes | 0 | 0 |

19 unterschiedliche native Zustandssequenzen bestätigten den geladenen
Szenenzustand. Alle zehn nativen Writerzähler blieben null; es gab keine
gezählte Lua-Speicheranforderung und keinen verweigerten Load. Alle zwölf
Dateien blieben bytegleich, es entstand keine neue Save-Datei. Nach dem
Schließen ausschließlich des eigenen Prozesses wurde die Original-DLL
SHA-256-geprüft wiederhergestellt. Die installierte Runtime bleibt 4494ef2.

Die [bereinigten Messwerte](validation/native-storage-reads-2026-11-18.json)
enthalten keine persönlichen Dateipfade, Save-/Steam-Kennungen oder
Prozessadressen. Die Messung zählt Aufrufe im Ladezeitraum. Ohne Dateinamen
und individuelle Callback-Zuordnung belegt sie nicht, welche genaue Datei
jeder Aufruf las oder dass alle Engine-Lesewege abgedeckt sind. Die
beobachteten Abschlussaufrufe wurden ebenfalls nur gezählt; ihre einzelnen
Ergebnisse und gelesenen Inhalte wurden nicht aufgezeichnet.

## Prüfungen und Folgearbeit

Die nativen Tests prüfen unveränderte Receiver, Namen, Buffer, Größen,
Offsets und 64-Bit-Handles sowie positive/negative Ergebnisse, tatsächlich
weitergereichte Daten und parallele Zähler. Sie prüfen außerdem die
unveränderte Standardsperre ohne Beobachtung, weiterhin blockierte Writer,
Seitenschutz, Integritätsverlust, Rückbau ohne Überschreiben fremder Einträge,
ein zweites abgewiesenes Anbinden und einen gültigen späten Weiterleitungsaufruf.
Die Writer-Proben verwenden synthetische Funktionen und keine echten Saves.

Als Nächstes sind Zielidentitäten und der asynchrone Abschlussweg einer
privaten Testkopie zu klären. Erst danach lässt sich eine isolierte
Lese-/Schreibumgebung entwerfen und ohne persönliche Save-/Cloud-Zugriffe
prüfen. Ein bloßer Ersatz von `FileRead`, ein früher Erfolg vor einem echten
asynchronen Abschluss oder eine geänderte Slotanzeige reichen dafür nicht.
Speicherumleitung, normales Speichern in einer isolierten Umgebung,
Kampffortschritt, Rejoin und zwei echte Steam-Konten bleiben offen.
