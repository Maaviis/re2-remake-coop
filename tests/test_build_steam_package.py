"""The drag-and-drop mod archive must include its Steam runtime and omit Markdown."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from tools.test_package.build_steam_package import BRIDGE_FILES, LOBBY_FILES, create_steam_archive


class SteamPackageBuildTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.package = root / 'verified-package'
        self.package.mkdir()
        self.output = root / 'RE2-Koop-test.zip'
        names = set((*LOBBY_FILES, *BRIDGE_FILES, 'LICENSE', 'scripts/protect_re2_test_saves.ps1'))
        names.update({
            'runtime/python.exe', 'runtime/python313.dll', 'runtime/python313.zip', 'runtime/python313._pth',
            'runtime/extra.pyd', 'third-party/REFramework-LICENSE.txt', 'third-party/NOTICE.md',
        })
        self.payload = {name: ('fixture:' + name).encode('utf-8') for name in names}
        for name, content in self.payload.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        manifest = {
            'schema': 1,
            'save_protection_schema': 1,
            'source_commit': 'a' * 40,
            'files': {name: hashlib.sha256(data).hexdigest() for name, data in self.payload.items()},
        }
        (self.package / 'bundle-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def test_write_failure_removes_partial_steam_zip_and_allows_retry(self):
        with (patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('disk full')),
              self.assertRaisesRegex(OSError, 'disk full')):
            create_steam_archive(self.package, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.zip.sha256').exists())
        result = create_steam_archive(self.package, self.output)
        self.assertEqual(result['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())

    def test_archive_contains_lobby_auto_bridge_and_runtime_without_repository_docs(self):
        result = create_steam_archive(self.package, self.output)
        with zipfile.ZipFile(self.output) as archive:
            names = set(archive.namelist())
            expected = set(LOBBY_FILES) | {'LICENSE', 'ZUERST_LESEN.txt', 're2-coop/build-info.json',
                                           're2-coop/scripts/protect_re2_test_saves.ps1'}
            expected.update(f're2-coop/{name}' for name in BRIDGE_FILES)
            expected.update({
                're2-coop/runtime/python.exe', 're2-coop/runtime/python313.dll',
                're2-coop/runtime/python313.zip', 're2-coop/runtime/python313._pth',
                're2-coop/runtime/extra.pyd', 're2-coop/third-party/REFramework-LICENSE.txt',
            })
            self.assertEqual(names, expected)
            self.assertFalse(any(name.lower().endswith('.md') for name in names))
            self.assertTrue({
                'reframework/autorun/re2_coop_cutscenes.lua',
                'reframework/autorun/re2_coop/cutscenes.lua',
                'reframework/autorun/re2_coop/cutscene_test_peer.lua',
                'reframework/autorun/re2_coop_guest_preview.lua',
                'reframework/autorun/re2_coop/door_state.lua',
                'reframework/autorun/re2_coop/world_item_state.lua',
                'reframework/autorun/re2_coop/interrupted_state.lua',
                'reframework/autorun/re2_coop_readonly_save_probe.lua',
                're2-coop/door_witness.py',
                're2-coop/interrupted_checkpoint.py',
                're2-coop/steam_snapshot_transfer.py',
                're2-coop/world_item_witness.py',
            } <= names)
            for name in LOBBY_FILES:
                self.assertEqual(archive.read(name), self.payload[name])
            for name in ('runtime/python.exe', 'steam_pose_bridge.py', 'wire.py'):
                self.assertEqual(archive.read(f're2-coop/{name}'), self.payload[name])
            self.assertEqual(archive.read('re2-coop/scripts/protect_re2_test_saves.ps1'),
                             self.payload['scripts/protect_re2_test_saves.ps1'])
            self.assertIn('Quellcommit: ' + 'a' * 40, archive.read('ZUERST_LESEN.txt').decode('utf-8-sig'))
            self.assertEqual(json.loads(archive.read('re2-coop/build-info.json')), {'source_commit': 'a' * 40})
        self.assertEqual(result['source_commit'], 'a' * 40)
        self.assertEqual(result['files'], len(expected))

    def test_changed_native_lobby_plugin_rejects_archive_before_creating_output(self):
        plugin = self.package / LOBBY_FILES[0]
        plugin.write_bytes(b'tampered native plugin')
        with self.assertRaisesRegex(ValueError, 'Package checksum mismatch'):
            create_steam_archive(self.package, self.output)
        self.assertFalse(self.output.exists())
