"""Build the drag-and-drop Steam lobby package from the verified CI package."""

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

if __package__:
    from .archive_package import _file
else:
    from archive_package import _file


LOBBY_FILES = (
    'reframework/plugins/re2_coop_steam_lobby_probe.dll',
    'reframework/plugins/re2_coop_steam_save_guard.dll',
    'reframework/autorun/re2_coop_lobby.lua',
    'reframework/autorun/re2_coop_save_catalog.lua',
    'reframework/autorun/re2_coop_observer.lua',
    'reframework/autorun/re2_coop_guest_pose.lua',
    'reframework/autorun/re2_coop_guest_preview.lua',
    'reframework/autorun/re2_coop_cutscenes.lua',
    'reframework/autorun/re2_coop/cutscenes.lua',
    'reframework/autorun/re2_coop/cutscene_test_peer.lua',
    'reframework/autorun/re2_coop/campaign_avatar.lua',
    'reframework/autorun/re2_coop/campaign_pose_scope.lua',
    'reframework/autorun/re2_coop_campaign_enemies.lua',
    'reframework/autorun/re2_coop/door_state.lua',
    'reframework/autorun/re2_coop/interrupted_state.lua',
    'reframework/autorun/re2_coop/death_observer.lua',
    'reframework/autorun/re2_coop/enemy_state.lua',
    'reframework/autorun/re2_coop/damage_observer.lua',
    'reframework/autorun/re2_coop/campaign_hits.lua',
    'reframework/autorun/re2_coop/guest_enemy_readback.lua',
    'reframework/autorun/re2_coop/guest_enemy_hp.lua',
    'reframework/autorun/re2_coop/lobby_input.lua',
    'reframework/autorun/re2_coop/main_menu.lua',
    'reframework/autorun/re2_coop_readonly_save_probe.lua',
    'reframework/autorun/re2_coop_load_state_observer.lua',
    'reframework/autorun/re2_coop/save_guard.lua',
    'reframework/autorun/re2_coop/host_checkpoint.lua',
    'reframework/autorun/re2_coop/save_protection.lua',
    'reframework/autorun/re2_coop/readonly_loader.lua',
    'reframework/autorun/re2_coop/new_game.lua',
    'reframework/autorun/re2_coop/prepared_load_pause.lua',
    'reframework/autorun/re2_coop/gameplay_pause.lua',
    'reframework/autorun/re2_coop/load_state.lua',
)
BRIDGE_FILES = (
    'campaign_hits.py', 'campaign_save_copy.py', 'campaign_setup.py', 'campaign_start.py', 'coop_checkpoint.py',
    'door_witness.py', 'enemy_live.py', 'enemy_witness.py', 'guest_enemy_file.py', 'interrupted_checkpoint.py',
    'guest_pose.py', 'load_preflight.py', 'load_witness.py', 'lobby_control.py', 'lobby_sync.py', 'observer.py',
    'pose_bridge.py', 'prepared_checkpoint.py', 'prepared_load_pause.py', 'readonly_save_control.py',
    'save_catalog.py', 'steam_pose_bridge.py', 'steam_snapshot_transfer.py',
    'save_protection.py', 'session.py', 'sync_model.py', 'wire.py',
    'protocol/__init__.py', 'protocol/snapshot_transfer.py', 'protocol/v1.py',
)


def create_steam_archive(package, output):
    package = Path(package).resolve(strict=True)
    output = Path(output).resolve()
    checksum = output.with_suffix('.zip.sha256')
    if output.is_relative_to(package) or output.exists() or checksum.exists():
        raise ValueError('Use a new archive path outside the input package')
    source = json.loads(_file(package, 'bundle-manifest.json').read_bytes())
    hashes = source['files']
    files = {name: name for name in (*LOBBY_FILES, 'LICENSE')}
    files.update({f're2-coop/{name}': name for name in BRIDGE_FILES})
    guard = 'scripts/protect_re2_test_saves.ps1'
    files[f're2-coop/{guard}'] = guard
    files.update({f're2-coop/{name}': name for name in hashes
                  if name.startswith(('runtime/', 'third-party/'))
                  and PurePosixPath(name).suffix.lower() != '.md'})
    payload = {}
    for target, name in files.items():
        content = _file(package, name).read_bytes()
        if hashes.get(name) != sha256(content).hexdigest():
            raise ValueError('Package checksum mismatch: ' + name)
        payload[target] = content
    for name in ('python.exe', 'python313.dll', 'python313.zip', 'python313._pth'):
        if f're2-coop/runtime/{name}' not in payload:
            raise ValueError('Missing portable Python file: ' + name)
    payload['re2-coop/build-info.json'] = json.dumps({'source_commit': source['source_commit']}).encode('ascii')
    payload['ZUERST_LESEN.txt'] = (
        'RE2 Koop – Steam-Entwicklungsbuild für Windows x64\n\n'
        '1. RE2 schließen. REFramework muss installiert sein (dinput8.dll neben re2.exe).\n'
        '2. Die beiden Ordner reframework und re2-coop aus dem ZIP neben re2.exe\n'
        '   kopieren. Gleichnamige alte Koop-Dateien vorher sichern.\n'
        '3. RE2 auf beiden PCs ganz normal über Steam starten und Multiplayer öffnen.\n'
        '   Beide Spieler verwenden dasselbe Mod-Paket.\n'
        '   Der Host erstellt die Lobby. Der Gast öffnet die Einladung in Steam\n'
        '   und bestätigt sie im Multiplayer-Menü.\n'
        '   Der Host sieht „Spiel starten“ dauerhaft. Beide Spieler müssen\n'
        '   bereit sein; danach startet der Host dort die Kampagne.\n\n'
        'Für den Kampagnentest auf beiden PCs isolierte Testprofile mit vorhandenen\n'
        'RE2-Systemdaten verwenden und Steam Cloud für RE2 deaktivieren. Für „Neues Spiel“\n'
        'die private Lobby öffnen und die Einladung auf dem zweiten PC annehmen. Beide\n'
        'wählen im Titelmenü der aktiven Lobby „Neues Spiel vorbereiten“. Der ursprüngliche\n'
        'Speicherordner bleibt bis zum Beenden von RE2 geschützt. Beide Spiele bleiben geöffnet.\n'
        'Der Host wählt „Neues Spiel“, Figur und Schwierigkeit. Beide bestätigen\n'
        'ihre Bereitschaft. Ein Szenario-Spielstand wird nur beim Slot-Laden benötigt.\n'
        'Einzeltest: Host-Lobby leer lassen, „Neues Spiel vorbereiten“ und danach\n'
        '„Solotest starten (Leon A, Normal)“ wählen. F5 schaltet im freien Spiel\n'
        'die Gastfigur ein oder aus. Sie übernimmt deine Bewegung. Bei einer erkannten Szene\n'
        'lässt F2 den Gast ankommen und startet die Wiedergabe. Für den ersten Test\n'
        'F2 einmal drücken und die Szene mit Bild und Ton weiterlaufen lassen.\n'
        'F6 fragt den Skip an, F2 stimmt als Gast zu,\n'
        'F3 lehnt als Gast ab. F4 fragt als Gast an, F7/F8 antwortet als Spieler.\n'
        'Mit zwei Spielern startet die Szene automatisch, sobald beide sie erreichen.\n'
        'Die Zwei-Konten-Abnahme im Spiel steht aus.\n\n'
        f'Quellcommit: {source["source_commit"]}\n'
    ).encode('utf-8-sig')
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(payload.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 2))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content)
    digest = sha256(output.read_bytes()).hexdigest()
    with checksum.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(f'{digest}  {output.name}\n')
    return {'source_commit': source['source_commit'], 'files': len(payload), 'sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create_steam_archive(args.package, args.output), indent=2))
