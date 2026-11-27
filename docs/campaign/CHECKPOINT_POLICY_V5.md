# Archivgebundener Ladeauftrag mit Schema 5

Sasha (@bySenom) entscheidet über die gemeinsame Schnittstelle und deren
Integration. Der Entwurf betrifft #155/#156 und #173: `arm`, den nativen
Probe-Aufrufer, beide Ladepausen und den anschließenden Weltvergleich.

## Aufrufe und gemeinsamer Bezug

Nach geprüftem Archivtransfer bereitet jede Rolle mit
`CampaignSetup.enable_checkpoint(selection, revision)` ihren Arbeitsordner vor.
Während des Wartens hält der Controller `CheckpointReadiness.refresh()` aktiv.
Die bereits existierende Auswahl `settings.coop_checkpoint` bleibt der Bezug.

Lobby-/Transportveröffentlichung muss während der Datei- und Pipeprüfungen
weiterlaufen. Im privaten E3-Treiber ließ die synchrone Übergabe den
Lobbybericht vor dem zweiten `_prepared_lobby` in `arm` veralten. Die
unveränderte produktive Prüfung wies ihn zurück. Mit unabhängiger
Veröffentlichung des modellierten Lobbyberichts besteht derselbe Build.
Die Drei-Sekunden-Fristen werden dafür nicht verlängert. Eine aktive
Vorbereitung bleibt erforderlich, bis der native Stagingbeleg bestätigt ist;
vor der gemeinsamen Startfreigabe endet die Erneuerung.

Für einen lokalen Abbruch kann derselbe Vorbereitungsworker
`CheckpointReadiness.cancel()` aufrufen. Er widerruft ausschließlich den
noch exakt passenden eigenen Workspace-Beleg. Eine inzwischen ersetzte
Vorbereitung und ein fehlender Beleg werden nicht überschrieben oder
wiederhergestellt. Der Aufruf ist mit `refresh()` auf demselben Worker
zu serialisieren; er beendet weder einen schon begonnenen nativen Load
noch den Mount und verändert keine Archivdatei. Die vorhandene native
Zulassungsprüfung weist den widerrufenen Beleg auch bei einer verspäteten
gemeinsamen Startfreigabe ab. Diese lokale Ergänzung ist E2 geprüft;
der unten genannte E3-Lauf bleibt dem unveränderten Build `17d862e` zugeordnet.

`arm(data, None, None, load=True, prepared_lobby=solo,
expected_game_pid=pid, expected_role=role, checkpoint={namespace, digest})`
prüft die drei unveränderten Archiv-/Arbeitsdateien und den aktuellen nativen
Import-, Katalog- und Workspace-Beleg erneut. Der Aufruf liest keinen alten
Einzelspieler-Slot und schreibt ausschließlich die lokale Ladepolicy.

Der gemeinsame `load_check` enthält zusätzlich `checkpoint_version: 1`,
`campaign_start: true`, `admission: 1` und den Manifest-Digest als `save_digest`.
Die Bereitschaft und die Capability dürfen erst nach vollständiger lokaler
Vorbereitung und gegenseitiger Prüfung desselben Builds gemeldet werden.
Für den Archivtransfer müssen beide Rollen denselben frischen Nonce verwenden.
Die Steam-Bridge handelt die Archivübertragung für die gewählte Revision aus.
Nach dem Import hält jeder lokale Controller seinen Vorbereitungsbeleg aktuell.
Beide Spieler bestätigen die Auswahl im Menü. Der Host startet den Ladeversuch,
wenn der Gast dieselbe Generation bestätigt hat und beide Controller bereit sind.

## Beispiel einer lokalen Policy

Die Beispielkennungen sind synthetisch. Host und Gast haben denselben
`checkpoint` und dieselben gemeinsamen Versuchsfelder. Prozess, Rolle,
Mitgliedschaft, Lua-Lauf, Vorbereitungsnonce und native Referenz sind lokal.

```json
{
  "schema": 5,
  "id": "11111111111111111111111111111111",
  "at": 1795788000,
  "load": true,
  "protection": {
    "game_pid": 1234,
    "run_id": "22222222222222222222222222222222",
    "campaign_namespace": "33333333333333333333333333333333"
  },
  "checkpoint": {
    "namespace": "44444444444444444444444444444444",
    "digest": "5555555555555555555555555555555555555555555555555555555555555555"
  },
  "preparation_id": "66666666666666666666666666666666",
  "reference": {"mode": 1, "slot_id": 0, "timestamp": "639001000000000000", "scenario": 0},
  "lobby_load": {
    "game_pid": 1234,
    "role": "H",
    "session_id": "77777777777777777777777777777777",
    "membership": {"session_id": "88888888888888888888888888888888", "revision": 7},
    "revision": 2,
    "attempt_id": "99999999999999999999999999999999",
    "save_digest": "5555555555555555555555555555555555555555555555555555555555555555",
    "guard_run_id": "local-lua-run"
  }
}
```

Die echte `id` wird aus dem kanonischen Digest von `lobby_load` abgeleitet.
Die Beispiel-ID ersetzt diese Berechnung nicht. Derselbe Versuch darf die
Zeit oder die lokale Vorbereitung einer bereits gestellten Policy nicht erneuern.

## Native Zulassung und Pause

Die Probe prüft Schema 5 sowohl beim Vormerken als auch beim gemeinsamen
Start erneut. Erst die bestehende beidseitige Startfreigabe erlaubt
`loader:start(reference, id, {preparation_id, guard_run_id})`.
`allow_checkpoint` bleibt eine einmalige lokale Zulassung; ein Schema-5-Auftrag
öffnet weder den gewöhnlichen Slot-Load noch ein neues Spiel.

Die Ladepause bindet Auswahl, Archiv-Digest, gemeinsame Revision und Versuch.
Nach Weltstart vergleicht `PreparedCheckpoint` die tatsächlich geladenen
nativen Checkpointwerte unter beiden gehaltenen Pausen. Erst die vorhandene
beidseitige Freigabe darf die Pausen lösen. Ein abweichender Digest,
Mitgliedschaftswechsel, verlorener Import oder abgelaufener Beleg verweigert
den Start. Ein fehlgeschlagener Start widerruft ausschließlich seine eigene
lokale Checkpoint-Zulassung. Keine Original- oder Archivdatei wird ersetzt.

## Vormerken und Vergleich nach dem Laden

Die Probe exportiert bei Schema 5 `staged_load` mit `id`, `requested_at`,
`checkpoint`, `preparation_id` und der lokalen `reference`. Die Bridge
bestätigt diesen Nonce und die Referenz gegen denselben frischen Workspace.
Ein vollständig ersetzter Import mit derselben Policy-ID kann die vorherige
native Vormerkung nicht weiterverwenden.

Der lokale Starter stellt `campaign_stage(..., checkpoint_available=True)`
und einen Stagingaufruf mit Auswahl, Versuch und Vorbereitungs-ID bereit.
Der Checkpoint-Controller ruft ihn einmal je Versuch auf. Während RE2 den
Auftrag vormerkt, veröffentlicht die Bridge weiter den Lobby-Status.
Die nachgelagerten Start-, Weltvergleichs-, Freigabe- und Kampfpfade
werden weiterverwendet. Die Zeugen erhalten eine streng validierte Referenz
aus dem nativen Slot-0-Beleg, keinen alten Einzelspieler-Katalogeintrag.

Der Snapshot des Checkpoint-Vergleichs verwendet Unterformat 4 im bestehenden
`prepared_load_checkpoint`-Umfang. Er enthält die vollständige gemeinsame
Archivwahl und den Digest des tatsächlich geladenen nativen Ladekopfs.
Die lokale Slot-Zeit ist nicht Teil des gemeinsamen Weltdigests. Schwierigkeit,
Szenario, beide Pausen und dieselbe gemeinsame Freigabe werden weiterhin
unabhängig geprüft. Der Unterbrechungsvergleich übernimmt ebenfalls die
ursprüngliche archivgebundene Lade-ID.

## Abnahmegrenze

Build `873368c` bestätigt zusätzlich in E3 den produktiven
`CheckpointStartController` mit den Komponenten seines tatsächlichen
121-Dateien-Steam-ZIP. Er bereitet den Import vor, stellt seine eigene
Policy, wartet auf den nativen Stagingbeleg und beendet die Erneuerung vor
dem modellierten gemeinsamen Start. Genau ein Load erreicht Leon A/Standard/
Karte 174/Gebiet 0 mit nativer Pause und Ladekopfzeuge. Der private Treiber
stellt keinen direkten `arm`-Aufruf. Controller-Schließen widerruft den eigenen
Beleg; Originalprofil, Cache und ACL sind geprüft zurückgesichert.
[E3-Controllerbericht](../../validation/native-checkpoint-controller-2026-11-27.json).
Die produktive Lobby-/UI-Schleife und ein tatsächlicher Steam-Gast bleiben
dabei außerhalb des Prüfstands. Der historische Nachweis unten behält `17d862e`.

Zwei simulierte Steam-Bridge-Schleifen bestätigen die Auswahl, einen Abbruch
vor der Zulassung und einen erneuten Versuch mit zwei lokalen Staging-IDs.
Ein separater Paartest prüft den anschließenden Weltvergleich und Austausch
der neuen Freigabe. Beide Tests erreichen E2.
Build `17d862e` ist zusätzlich in echtem RE2 geprüft (E3): leeres isoliertes
Szenarioprofil, reguläre Checkpoint-Vorbereitung, acht Erneuerungen über
8,437 Sekunden, produktive Schema-5-Policy und nativer Stagingbeleg. Nach
modellierter gemeinsamer Startfreigabe folgen genau ein erlaubter Load,
`scene_loaded`, Slot 0/Leon A/Standard/Karte 174/Gebiet 0 und der produktive
Ladekopfzeuge unter nativer Pause (Snapshot-Unterformat 4). Originalprofil,
Steam-Dateicache und ACL sind geprüft zurückgesichert.
Elf echte Originaldateien blieben separat gesperrt. Dieser Test enthält
eine echte Hostinstanz, ein Steam-Konto und eine modellierte Lobby/Gegenstelle;
er löst die Pause nicht und ersetzt keinen gemeinsamen Controllerlauf.
[Bereinigter E3-Bericht](../../validation/native-checkpoint-schema5-policy-2026-11-27.json).
Die historischen E3-Läufe behalten ihre jeweils genannten Quellbuilds.
Normaler Steam-Neustart, neue Lobby, Gast mit leerem Szenarioprofil und
beidseitige gemeinsame Fortsetzung bleiben auf zwei echten PCs zu prüfen.
