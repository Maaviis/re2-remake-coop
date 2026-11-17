"""Exercise rollback using a disposable game/Steam fixture, never real saves."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shutil
import os
import json
import hashlib

SOURCE = Path(__file__).resolve().parents[1] / 'tools/test_package/test_mod.py'
spec = importlib.util.spec_from_file_location("test_mod", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class InstallerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.package = root / 'package'
        self.package.mkdir()
        fixture_files = {
            'reframework/autorun/re2_coop_probe.lua': b'project Lua fixture',
            'reframework/plugins/re2_coop_steam_lobby_probe.dll': b'project lobby DLL fixture',
            'reframework/plugins/re2_coop_steam_save_guard.dll': b'project save DLL fixture',
        }
        for name, content in fixture_files.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.package / 'bundle-manifest.json').write_text(json.dumps({
            'schema': 1, 'save_protection_schema': 1, 'source_commit': 'fixture-only',
            'install_files': list(fixture_files),
            'files': {name: hashlib.sha256(content).hexdigest() for name, content in fixture_files.items()}}))
        context = patch.object(mod, 'ROOT', self.package)
        context.start()
        self.addCleanup(context.stop)
        self.game, self.steam = root / "game", root / "steam"
        self.game.mkdir()
        (self.game / "re2.exe").write_bytes(b"fixture")
        (self.game / "dinput8.dll").write_bytes(b"fixture" * 1024)
        self.config = b"REFrameworkConfig_MenuOpen=true\r\nREFrameworkConfig_RememberMenuState=false\r\n"
        (self.game / "re2_fw_config.txt").write_bytes(self.config)
        self.files = []
        for name in mod.FOLDERS:
            folder = self.game / "reframework" / name
            folder.mkdir(parents=True)
            original = folder / "existing.file"
            original.write_bytes((name + " original").encode())
            self.files.append((original, original.read_bytes()))
        self.save = self.steam / "userdata/123/883710/remote/win64_save/data000.bin"
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b"unmodified personal save fixture")
        self.source_link = root / "vortex-source.lua"
        self.source_link.write_bytes(b"external mod fixture")
        self.link = self.game / "reframework/autorun/vortex-link.lua"
        try:
            self.link.symlink_to(self.source_link)
            self.symbolic = True
        except OSError as exc:
            if getattr(exc, 'winerror', None) != 1314:
                raise
            os.link(self.source_link, self.link)
            self.symbolic = False
        for name, value in (("steam_root", self.steam), ("processes", [])):
            context = patch.object(mod, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        # A test deployment must not write an installation pointer into the shareable package.
        self.real_write = mod.write
        def fixture_write(path, value):
            if path == self.package / "installation.json":
                return
            self.real_write(path, value)
        context = patch.object(mod, "write", side_effect=fixture_write)
        context.start()
        self.addCleanup(context.stop)

    def assert_original(self):
        for path, content in self.files:
            self.assertEqual(path.read_bytes(), content)
        if self.symbolic:
            self.assertTrue(self.link.is_symlink())
        else:
            self.assertTrue(self.link.samefile(self.source_link))
        self.assertEqual(self.link.read_bytes(), b"external mod fixture")
        self.assertEqual(self.source_link.read_bytes(), b"external mod fixture")
        self.assertEqual((self.game / "re2_fw_config.txt").read_bytes(), self.config)
        self.assertEqual(self.save.read_bytes(), b"unmodified personal save fixture")

    def test_install_and_restore_even_when_installed_file_changed(self):
        mod.install(self.game)
        state = mod.installed(self.game)
        self.assertTrue(state["active"])
        backup_save = Path(state["backup"]) / "saves/123/883710/remote/win64_save/data000.bin"
        self.assertEqual(backup_save.read_bytes(), self.save.read_bytes())
        (self.game / "reframework/autorun/re2_coop_probe.lua").write_bytes(b"changed by deployment")
        with self.assertRaisesRegex(ValueError, "Installierte Datei"):
            mod.installed(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        self.assert_original()

    def test_copy_failure_restores_original_mod_directories(self):
        original_copy = shutil.copy2
        def copy(source, target, *args, **kwargs):
            if Path(target).parent.resolve() == (self.game / "reframework/autorun").resolve():
                raise OSError("simulated deployment failure")
            return original_copy(source, target, *args, **kwargs)
        with patch.object(mod.shutil, "copy2", side_effect=copy):
            with self.assertRaisesRegex(OSError, "simulated deployment"):
                mod.install(self.game)
        self.assert_original()

    def test_running_re2_refuses_installation_before_mutation(self):
        with patch.object(mod, "processes", return_value=[{"pid": 123}]):
            with self.assertRaisesRegex(ValueError, "RE2 bitte"):
                mod.install(self.game)
        self.assertFalse((self.game / mod.APP).exists())
        self.assert_original()

    def test_legacy_bundle_cannot_install_before_mutating_mods(self):
        path = self.package / 'bundle-manifest.json'
        manifest = mod.read(path)
        manifest.pop('save_protection_schema')
        mod.write(path, manifest)
        with self.assertRaisesRegex(ValueError, 'Altes Testpaket'):
            mod.install(self.game)
        self.assertFalse((self.game / mod.APP).exists())
        self.assert_original()

    def test_changed_packaged_guard_cannot_install(self):
        (self.package / 'reframework/plugins/re2_coop_steam_save_guard.dll').write_bytes(b'tampered fixture')
        with self.assertRaisesRegex(ValueError, 'Paketdatei'):
            mod.install(self.game)
        self.assertFalse((self.game / mod.APP).exists())
        self.assert_original()

    @unittest.skipUnless(os.name == 'nt', 'real Windows sharing required')
    def test_status_writer_survives_a_brief_reader_without_delete_sharing(self):
        from threading import Timer
        from save_file_guard import SaveFileLocks

        status = self.package / 'synthetic-protection.json'
        status.write_bytes(b'{"active":false}')
        with SaveFileLocks([status]) as reader:
            release = Timer(0.03, reader.close)
            release.start()
            try:
                mod.write(status, {'active': True, 'run_id': 'fixture'})
            finally:
                release.join(timeout=1)
        self.assertEqual(mod.read(status), {'active': True, 'run_id': 'fixture'})
        self.assertEqual(list(self.package.glob('*.tmp')), [])

    @unittest.skipUnless(os.name == 'nt', 'real Windows sharing required')
    def test_permanent_reader_conflict_preserves_original_and_cleans_temporary_file(self):
        from save_file_guard import SaveFileLocks

        status = self.package / 'synthetic-protection.json'
        original = b'{"active":false}'
        status.write_bytes(original)
        with SaveFileLocks([status]):
            with self.assertRaises(PermissionError):
                mod.write(status, {'active': True})
        self.assertEqual(status.read_bytes(), original)
        self.assertEqual(list(self.package.glob('*.tmp')), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
