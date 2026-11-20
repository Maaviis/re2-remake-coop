# Native Todesbeobachtung und der Null-HP-Grenzfall

Die Mod darf einen vollständigen Todesablauf nicht allein aus HP=0 ableiten.
Ein kontrollierter Versuch am 18. November 2026 bestätigte zwar null HP und
die nativen Lebens-/Todesflags eines echten Kampagnengegners, aber keinen
zusätzlichen Kill und keinen aufgezeichneten `onDead`-Callback. Seine KI
war deaktiviert. Der Versuch ist eine Zustandsmessung, keine bestandene
Todes- oder Zwei-Spieler-Synchronisation.

## Separater passiver Beobachter

`re2_coop/death_observer.lua` beobachtet ausschließlich
`app.ropeway.enemy.em0000.Em0000ThinkBase.onDead`. Für RE2/TDB 70 werden
Rückgabe-/Parameter-/Feldtypen geprüft. Zusätzlich muss die konkrete,
tatsächlich gemessene Klasse `Em0000Think` dieselbe Methode mit demselben
nativen Einstiegspunkt und derselben deklarierenden Klasse auflösen.
Andere Auflösungen und fehlende Einstiegspunkte werden abgewiesen.

`new()` bereitet diese Metadaten vor und installiert noch keinen Hook.
Erst `start()` verlangt einen abgeschlossenen Szenenladezustand, verlassenen
Titel-/Ladeflow und freien Save-Manager. Fehlende Manager oder fehlgeschlagene
Abfragen erlauben keine Registrierung. Eine erfolgreiche Registrierung
wird nicht wiederholt; ein gestoppter Beobachter kann nicht neu starten.

Der Hook lässt den Originalaufruf und dessen Rückgabewert unverändert.
Beim Eintritt kopiert er nur GUID, Zeitpunkt und gegebenenfalls die
vorhandenen HP in Lua-Grundwerte. Fehlende HP werden ausdrücklich markiert,
fehlende/ungültige GUIDs als Lesefehler gezählt. Nach dem Originalaufruf
verwendet er keine nativen Objektverweise mehr. `phase=returned` bezeichnet
nur die Rückkehr aus diesem Callback. `hp_on_entry` ist eine Beobachtung
am Callback-Eintritt, kein nachgewiesener Wert vor dem ursprünglichen Treffer.
Es werden weder Spiel-Getter noch Datei-/Netzwerkoperationen im Hook aufgerufen.

Die Historie ist auf 128 Einträge begrenzt; steigende Sequenz und
`discarded` zeigen ausgelassene ältere Aufzeichnungen an. `snapshot()`
liefert Kopien. Ein leerer Puffer ist kein Todesereignis. Die Registrierung
und die geprüfte Methodenauflösung beweisen außerdem nicht, dass ein
Callback tatsächlich ausgelöst und vollständig erfasst wurde.

Die optionale Datei
`reframework/diagnostics/re2_coop_death_observer.lua` ist im Nutzerpaket
nicht aktiviert. Sie schreibt außerhalb der Hooks alle sechs Updates
`re2_coop_death_observer.json` mit Schema 1, Quelle/TDB, VM-Laufkennung,
Berichtssequenz, Zeit, Umfang `native_em0000_on_dead_callbacks` und
Verfügbarkeit. Vor der Registrierung meldet sie Nichtverfügbarkeit.
Ein Reset entfernt die verfügbare Zustandsprobe und verhindert weitere
Veröffentlichung aus derselben Diagnose. Leere Lua-Listen können als JSON
`null` erscheinen; deren Zähler bleibt null.

Dieser Export ist eine lokale Diagnose. Eine spätere Netzwerkanbindung
muss Prozess, Load, Weltzustand und Steam-Sitzung zusätzlich binden sowie
Fristen, verlorene Einträge und Wiederholung behandeln. Ein `available=true`
ist keine gemeinsame Spielfreigabe und kein bestätigter Welt-Todeszustand.
Weitere Gegnertypen, Rückkehr-/Neuladepfade und gemeinsamer Rejoin fehlen.

## Geschützter nativer Versuch

Getestet wurde die geschützte Runtime `4494ef2` mit RE2 Build 11636119,
REFramework d1461375 und ausschließlich dem freigegebenen alten Slot 4
vom 11.11.2026. Die vererbten Dateisperren und der native Steam-Writer-Guard
blieben aktiv. Bewegungen und Native-API-Aufrufe erfolgten ausschließlich
über das Terminal in der eigenen Instanz.

Nach dem bekannten Treppenweg waren fünf Controller aktiv. Der unveränderte
positive HP-Adapter bestätigte zunächst erneut 770 → 769 HP mit lokal
erzeugter Hostquelle. Anschließend wurde diese Quelle abgeschaltet.
Erst danach rief der private Test für denselben gewöhnlichen Zombie genau
einmal `HitPointController.addDamage(System.Int32)` mit 769 auf. GUID,
Typ, InheritID, HP und beide Schutzflags wurden unmittelbar zuvor geprüft;
`NoDamage` und `NoDead` waren falsch und wurden nicht verändert.

| Beobachtung | Ergebnis |
|---|---|
| Direkte native Schadensanforderung | Einmal 769 bei zuvor 769 HP |
| Unabhängige Zustandsproben | 60 unterschiedliche native Sequenzen über zehn Sekunden |
| HP-/Lebensflags danach | HP=0, `is_dead=true`, `is_live=false` |
| Controller-/KI-Zustand | Weiter `active=true`, `standby=true`, `think_enabled=false` |
| Globaler Killzähler | Vorher 19, danach 19 |
| Aufgezeichnete `onDead`-Callbacks | Null; null Lesefehler; native Hook-Registrierung im Framework-Protokoll bestätigt |
| Speicherschutz | Ein erlaubter Load, null verweigerte Loads, keine gezählte Lua-Speicheranforderung; alle zehn nativen Writerzähler null nach der Schadensanforderung |
| Dateivergleich und Rückbau | Zwölf bytegleiche Dateien, keine neue Save-Datei; eigene Instanz geschlossen und temporäre Skripte entfernt |

Die [bereinigten Messwerte](validation/native-point-damage-2026-11-18.json)
enthalten keine persönliche Steam-Kennung, Save-GUID oder Prozessadresse.
Der private Rohbericht bleibt lokal; sein SHA-256 erlaubt den Abgleich.
Eine zusätzliche rein lesende Titelbildprüfung bestätigte die identische
Methodenauflösung der konkreten und der Basisklasse sowie die verweigerte
Aktivierung der finalen Beobachterfassung vor einem geladenen Spielzustand.
Dabei wurde keine Kampagne geladen.

Eine frühere Probe blieb vor jeder Schadensanforderung beim Laden ohne
frische Frameberichte; das Protokoll zeigte wiederholte D3D12-Neuinitialisierung.
Der unveränderte Kontrollaufbau erreichte anschließend drei frische
Zustandsframes. Nach der späteren Hook-Registrierung durchlief der finale
Versuch Laden, Bewegung und native Schadensanforderung. Die genaue Ursache
des ersten Stillstands ist offen; eine allgemeine Lade-/Rejoinstabilität
wird daraus nicht abgeleitet. Alle diese Läufe ließen zwölf Dateien unverändert.

## Konsequenz für die Koop-Entwicklung

Eine aktive Listenmitgliedschaft belegt in diesem Fall keine laufende KI.
Null HP und die zurückgegebenen Flags sind ebenso wenig ein vollständiger
Nachweis für Todesreaktion, Körperzustand, Kill-Zuordnung, Beute oder
Skriptnebenwirkungen. Der positive HP-Adapter bleibt unverändert; ein
allgemeiner Null-HP-Todesanwender wird durch diesen Versuch nicht freigegeben.

Als Nächstes muss ein tatsächlich simulierter Gegner beziehungsweise der
ursprüngliche Trefferpfad mit Zustands-/Callbackvergleich geprüft werden.
Für zwei unabhängig handelnde Spieler ist außerdem zu klären, wie der
Host relevante Szenen und Gegner-KI für beide Spielerbereiche aktiv hält.
Der natürliche Treffer, ein positiver nativer Callback, vollständige
Todesanwendung und die Abnahme mit zwei echten Instanzen bleiben offen.
