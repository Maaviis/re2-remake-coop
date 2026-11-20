# Passive native Gegner-Treffercallbacks

Dieser Entwurf gehört zum Arbeitspaket [Spieler und Kampf #2](https://github.com/Maaviis/re2-remake-coop/issues/2) und baut auf #87 auf. Er ergänzt einen **rein passiven Diagnosebeobachter** für `app.ropeway.EnemyController.HitController_OnHitDamage(app.Collision.HitController.DamageInfo)`. Er überträgt und verändert keine Kampfwerte.

**Nachträglicher Sicherheitsbefund:** Beim regulären Weitergehen über den nächsten Kontrollpunkt wurde `data000.bin` trotz aktiv gemeldeter 26 Lua-Guard-Hooks verkürzt. Die lokale Originaldatei wurde aus der zuvor geprüften Sicherung wiederhergestellt; manuelle Slots waren unverändert. Die bisherige Testinstallation und ihr Paket sind bis zur Korrektur des Speicherschutzes zurückgezogen. Die unten beschriebene Lua-Sperre allein schützt die Dateien nachweislich nicht vollständig. Diese Trefferdiagnose darf damit derzeit nicht für weitere Kampagnenversuche eingesetzt werden.

## Quelle und Daten

Vor dem Hook prüft das Modul TDB 70, die Instanz-/Void-Signatur des Callbacks, den Referenztyp des Arguments und alle verwendeten Feldtypen. Die native Typenabfrage in RE2 Build 11636119 mit REFramework d1461375 bestätigte `DamageInfo` als Referenzobjekt mit 208 Bytes, abgeleitet von `app.Collision.HitInfo`.

Der Pre-Hook kopiert die Gegner-GUID direkt aus dem Callback-Empfänger sowie dessen HP-Feld und die primitiven DamageInfo-Werte `OriginalDamage`, `Damage`, `Wince`, `Break`, `IsKill` und `IsArmored`. Der Post-Hook kopiert die Werte erneut. Die Rohadressen von Gegner, HP, Angriffseigentümer und Waffe werden nicht exportiert. `attacker` vergleicht den Angriffseigentümer mit dem zuletzt außerhalb des Hooks erfassten lokalen Spielerobjekt; ohne solche Bindung lautet der Wert `unknown`.

**Die HP-Werte heißen bewusst `hp_on_entry` und `hp_on_exit`:** Der Callback kann nach einer bereits erfolgten HP-Änderung laufen. Aus unveränderten Callback-HP darf keine Aussage über fehlenden Schaden folgen. `IsKill` ist das Feld des Trefferarguments; es ersetzt weder den direkten nativen Todeszustand noch einen bestätigten Gegner-Killzähler. Null HP wird nicht als Tod interpretiert. Trefferreaktion, Animation und KI müssen getrennt belegt werden.

Der Beobachter führt innerhalb der nativen Hooks keine verwalteten Spielmethoden, Setter oder Dateizugriffe aus. GUID- und Wertkopien lesen Felder. Verschachtelte Aufrufe besitzen ihren eigenen Speicher über `thread.get_hook_storage()`. Der Pre-Hook lässt den Originalaufruf laufen; der Post-Hook gibt dessen unveränderten Rückgabewert zurück. Lesefehler erhöhen `read_errors` und erzeugen keinen Teilbefund. Der Ring enthält höchstens 128 abgeschlossene Callbacks; `discarded` meldet verdrängte Einträge. Die Sequenz beschreibt die Reihenfolge abgeschlossener Callbacks, auch bei Verschachtelung.

## Optionale Installation

Nur in einer gesicherten Entwicklungsinstallation bei beendetem RE2:

1. `reframework/autorun/re2_coop/damage_observer.lua` unter denselben Modulpfad kopieren.
2. `reframework/diagnostics/re2_coop_damage_observer.lua` in den flachen `reframework/autorun`-Ordner kopieren.
3. RE2 starten. Der Export `reframework/data/re2_coop_damage_observer.json` enthält `run_id`, `observed_at`, `scope=enemy_damage_callback` und `state` mit Sequenz, Fehler-/Verdrängungszählern und Ereignissen. Ein leeres Lua-Array kann als JSON `null` erscheinen.
4. Einen regulären eigenen Schuss auf einen aktiven Gegner abgeben. Bei einem Callback die GUID mit dem nativen Gegnerleser abgleichen und HP, direkten Todeszustand und Killzähler separat vor/nach dem Treffer vergleichen. Veraltete Reports, eine andere VM oder ein anderer Checkpoint dürfen später nicht als Netzwerkereignis übernommen werden.
5. Für die Entfernung RE2 beenden, die Diagnose entfernen und den vorherigen Modulstand zurückstellen. Das Laufzeit-`stop()` verhindert weitere Erfassung, ersetzt keinen Skript-/Spielneustart zur Entfernung der nativen Hooks.

Der vorhandene Beobachter ist eine lokale Historie mit begrenzter Länge. Er besitzt noch keine Checkpoint-/Hostautoritätsbindung, keine Deduplizierung desselben Treffers über mehrere Systeme, keine Transportbestätigung und keinen Gastanwender. Er gehört deshalb nicht in den freigegebenen Netzwerk-Ereignispfad oder in einen automatischen HP-Abgleich.

## Prüfungen am 17.11.2026

Die Lua-Regression prüft das Fortsetzen des nativen Aufrufs und dessen Rückgabewert, kopierte Werte statt geteilter Tabellen, zwei verschachtelte Empfänger, vollständige Abweisung defekter Schnittstellen vor dem Hook, Fehler auf beiden Hookseiten, unsigned GUID-Felder, fehlende Spielerbindung, Null-HP ohne erfundenen Kill, begrenzte Historie und Stoppen. Die Tests verwenden nachgebildete native Bindings.

In einer echten geschützten RE2-Instanz wurde ausschließlich der freigegebene alte Slot vom 11.11.2026 geladen. Der Hook ließ sich mit allen Schnittstellenprüfungen installieren. Der normale kurze Laufweg aktivierte fünf bekannte Gegnercontroller; vier waren bereits tot, einer hatte 770 HP. Die passive Diagnose blieb bei null Lesefehlern.

Eine **private, nicht mitgelieferte** native Eingabeprobe bestätigte den Zielmodus mit `Petient.HOLD=16` sowie die Clips `pl10_0150_HG_Hold_Start_R0` und `pl10_0160_HG_Hold_Idle_Loop`. Ein zunächst zu früher kurzer Angriffsimpuls verbrauchte keine Munition. Nach dem beobachteten Hold-Idle-Clip und höchstens sechs erzwungenen Angriffsupdates sank die vorhandene Munition von vier auf drei. Beide eigenen Force-Bitbereiche wurden anschließend als null zurückgelesen; alle temporären Testhelfer sind entfernt, die vorher installierte Mod blieb unverändert erhalten. Der Guard meldete einen erlaubten alten Ladevorgang, keine verweigerte Anforderung und keine abgefangenen Schreibaufrufe. Alle zwölf Speicherdateien blieben unverändert.

**Dieser Schuss lieferte keinen Gegnertreffer:** null Callbacks, null Lesefehler, lebender Gegner weiter bei 770 HP. Damit sind native Installation und die begrenzte Zieleingabe belegt; ein positiver Callback, seine Reihenfolge im echten Schadensablauf, normale Killzuordnung, Boss-/Skriptfälle und jede Zwei-Instanzen-Abnahme stehen weiterhin aus. Es wurde kein Schaden durch einen HP-Setter oder einen direkt aufgerufenen Schadensarbeiter erzeugt.
