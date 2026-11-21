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
import io
import sys
from contextlib import ExitStack, redirect_stderr
from datetime import date

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
            'reframework/autorun/re2_coop/save_guard.lua': b'project guard fixture',
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

    def test_installation_records_an_explicit_canonical_save_date(self):
        mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual(mod.installed(self.game)['allow_save_date'], '2026-04-08')
        self.assertNotIn('allow_save_date', mod.verify_bundle())
        mod.restore(self.game, mod.installation_state(self.game))
        self.assert_original()

    def test_date_can_change_after_uninstall_while_preserving_the_inactive_package(self):
        mod.install(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        previous = (self.game / mod.APP / 'install-state.json').read_bytes()
        mod.install(self.game, allow_save_date='2026-04-08')
        state = mod.installed(self.game)
        archived = Path(state['backup']) / 'previous-installation'
        self.assertEqual((archived / 'install-state.json').read_bytes(), previous)
        self.assertEqual(state['allow_save_date'], '2026-04-08')
        mod.restore(self.game, state)
        self.assert_original()

    def test_reinstall_copy_failure_leaves_the_inactive_package_in_place(self):
        mod.install(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        previous = (self.game / mod.APP / 'install-state.json').read_bytes()
        original_copy = shutil.copy2
        def fail_payload_copy(source, target, *args, **kwargs):
            if Path(source).is_relative_to(self.package):
                raise OSError('copy failed')
            return original_copy(source, target, *args, **kwargs)
        with patch.object(mod.shutil, 'copy2', side_effect=fail_payload_copy):
            with self.assertRaisesRegex(OSError, 'copy failed'):
                mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual((self.game / mod.APP / 'install-state.json').read_bytes(), previous)
        self.assert_original()

    def test_active_or_unknown_existing_installation_is_not_displaced(self):
        mod.install(self.game)
        app = self.game / mod.APP
        original = (app / 'install-state.json').read_bytes()
        before = set(self.game.glob('re2-coop-backup-*'))
        with self.assertRaises(ValueError):
            mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual((app / 'install-state.json').read_bytes(), original)
        self.assertEqual(set(self.game.glob('re2-coop-backup-*')), before)
        mod.restore(self.game, mod.installation_state(self.game))
        (app / 'install-state.json').unlink()
        with self.assertRaises(ValueError):
            mod.install(self.game, allow_save_date='2026-04-08')
        self.assertTrue((app / 'bundle-manifest.json').is_file())
        self.assertEqual(set(self.game.glob('re2-coop-backup-*')), before)
        self.assert_original()

    def test_interrupted_installation_is_not_mistaken_for_a_completed_restore(self):
        mod.install(self.game)
        path = self.game / mod.APP / 'install-state.json'
        interrupted = mod.read(path)
        interrupted['active'] = False
        self.real_write(path, interrupted)
        previous = path.read_bytes()
        before = set(self.game.glob('re2-coop-backup-*'))
        with self.assertRaises(ValueError):
            mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(set(self.game.glob('re2-coop-backup-*')), before)
        self.assertTrue((Path(interrupted['backup']) / 'original-autorun' / 'existing.file').is_file())
        mod.restore(self.game, interrupted)
        self.assert_original()

    def test_failed_package_rename_restores_the_previous_inactive_directory(self):
        mod.install(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        previous = (self.game / mod.APP / 'install-state.json').read_bytes()
        original_rename = Path.rename
        def fail_staging_rename(path, target):
            if path.name == 'package':
                raise PermissionError('fixture rename failure')
            return original_rename(path, target)
        with patch.object(Path, 'rename', fail_staging_rename):
            with self.assertRaisesRegex(PermissionError, 'fixture rename failure'):
                mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual((self.game / mod.APP / 'install-state.json').read_bytes(), previous)
        self.assert_original()

    def test_reinstall_from_inside_the_inactive_package_is_rejected(self):
        mod.install(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        app = self.game / mod.APP
        before = set(self.game.glob('re2-coop-backup-*'))
        with patch.object(mod, 'ROOT', app), self.assertRaisesRegex(ValueError, 'externe'):
            mod.install(self.game, allow_save_date='2026-04-08')
        self.assertEqual(set(self.game.glob('re2-coop-backup-*')), before)
        self.assertFalse(mod.read(app / 'install-state.json')['active'])
        self.assert_original()

    def test_existing_package_directory_link_is_not_followed(self):
        mod.install(self.game)
        mod.restore(self.game, mod.installation_state(self.game))
        app = self.game / mod.APP
        target = app.rename(self.game / 'preserved-inactive-package')
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(target), str(app))
        else:
            app.symlink_to(target, target_is_directory=True)
        before = set(self.game.glob('re2-coop-backup-*'))
        try:
            with self.assertRaisesRegex(ValueError, 'Verknuepfung'):
                mod.install(self.game, allow_save_date='2026-04-08')
            self.assertEqual(set(self.game.glob('re2-coop-backup-*')), before)
            self.assertFalse(mod.read(target / 'install-state.json')['active'])
            self.assert_original()
        finally:
            if os.name == 'nt':
                app.rmdir()
            else:
                app.unlink()

    def test_invalid_save_dates_are_rejected_before_installation_mutates_files(self):
        for value in ('2026-02-30', '2026-4-8', '20260408', '2026-W15-3', '', None, 20260408):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'YYYY-MM-DD'):
                mod.install(self.game, allow_save_date=value)
            self.assertFalse((self.game / mod.APP).exists())
            self.assertEqual(list(self.game.glob('re2-coop-backup-*')), [])
            self.assert_original()

    def ready_load(self, *, allow_save_date='2026-04-08', catalog_date='2026-04-08', legacy=False):
        from tests.test_save_catalog import source
        from tests.test_save_protection import write_protection
        import datetime as dt
        mod.install(self.game, allow_save_date=allow_save_date)
        data = self.game / 'reframework/data'
        if legacy:
            path = self.game / mod.APP / 'install-state.json'
            state = mod.read(path)
            state.pop('allow_save_date')
            self.real_write(path, state)
        catalog = source()
        day = dt.date.fromisoformat(catalog_date)
        timestamp = str((day - dt.date.min).days * 864_000_000_000)
        catalog['entries'][1]['timestamp'] = timestamp
        self.real_write(data / 're2_coop_save_catalog.json', catalog)
        write_protection(data)
        self.real_write(data / 're2_coop_save_guard.json', {
            'schema': 1, 'active': True, 'hooks': 26, 'at': 100, 'denied_loads': 0,
            'allowed_load_calls': 0, 'in_title': True, 'busy': False,
            'load_menu_busy': False, 'title_open': True, 'command_id': '',
            'command_error': '', 'load_request_id': '', 'protection_active': True,
            'protection': {'game_pid': 42, 'run_id': 'a' * 32}})
        self.real_write(data / 're2_coop_test_session.json', {'active': True, 'id': 'a' * 32, 'game_pid': 42})
        return data, timestamp

    def test_load_uses_the_installation_date_with_real_catalog_and_policy_validation(self):
        data, timestamp = self.ready_load()
        with (patch.object(mod, 'game_process', return_value={'pid': 42}),
              patch('readonly_save_control.time.time', return_value=100),
              patch('readonly_save_control.wait_for_result') as wait):
            mod.load(self.game, 'scenario:4')
        policy = mod.read(data / 're2_coop_save_policy.json')
        self.assertEqual(policy['reference']['timestamp'], timestamp)
        self.assertIs(policy['load'], True)
        self.assertEqual(mod.read(data / 're2_coop_test_load.json')['date'], '2026-04-08')
        wait.assert_called_once_with(data, policy['id'], load=True, timeout=90, require_pause=False)

    def test_load_rejects_a_save_outside_the_recorded_date_before_queuing(self):
        data, _ = self.ready_load(catalog_date='2026-11-11')
        with (patch.object(mod, 'game_process', return_value={'pid': 42}),
              patch('readonly_save_control.time.time', return_value=100),
              self.assertRaises(ValueError)):
            mod.load(self.game, 'scenario:4')
        self.assertFalse((data / 're2_coop_save_policy.json').exists())
        self.assertFalse((data / 're2_coop_lobby_view.json').exists())

    def test_prepared_start_refuses_missing_acl_before_acquiring_file_locks(self):
        mod.install(self.game)
        with (patch('save_file_guard.SaveFileLocks') as locks,
              patch('readonly_save_control._storage_guard_active', return_value=False),
              self.assertRaisesRegex(ValueError, 'Windows-ACL')):
            mod.start(self.game, 'host', prepared_save_directory=self.save.parent)
        locks.assert_not_called()

    def test_prepared_starter_passes_the_native_source_on_both_roles(self):
        mod.install(self.game, allow_save_date='2026-04-08')
        for role, wire_role in (('host', b'H'), ('guest', b'G')):
            with self.subTest(role=role), ExitStack() as stack:
                child, pipe, bridge = self.prepared_starter_fixture(stack)
                mod.start(self.game, role, prepared_save_directory=self.save.parent)
                args, kwargs = bridge.call_args
                self.assertEqual(args[2], wire_role)
                self.assertIs(args[1], pipe)
                self.assertEqual(kwargs['load_source'].directory, self.save.parent.resolve())
                self.assertEqual(kwargs['load_source'].catalog.allow_date, date(2026, 4, 8))
                child.terminate.assert_not_called()

    def test_prepared_starter_retains_the_path_used_by_the_acl_wrapper(self):
        (self.save.parent / 'alias').mkdir()
        supplied = self.save.parent / 'alias' / '..'
        mod.install(self.game, allow_save_date='2026-04-08')
        with ExitStack() as stack:
            _, _, bridge = self.prepared_starter_fixture(stack)
            guard = stack.enter_context(patch('readonly_save_control._storage_guard_active',
                                               side_effect=lambda directory: directory == supplied))
            mod.start(self.game, 'host', prepared_save_directory=supplied)
            self.assertEqual(bridge.call_args.kwargs['load_source'].directory, supplied.resolve())
            self.assertEqual(guard.call_count, 2)
        session = mod.read(self.game / 'reframework/data/re2_coop_test_session.json')
        self.assertEqual(session['prepared_save_directory'], str(supplied))

    def test_campaign_start_callback_preserves_the_installation_save_pin(self):
        from tests.test_save_catalog import source

        mod.install(self.game, expected_slot4='1234')
        data = self.game / 'reframework/data'
        self.real_write(data / 're2_coop_save_catalog.json', source())
        with ExitStack() as stack:
            _, _, bridge = self.prepared_starter_fixture(stack)
            arm = stack.enter_context(patch('readonly_save_control.arm'))

            def click(*args, stage_campaign, **kwargs):
                from readonly_save_control import read_active_guard

                guard = {'denied_loads': 0, 'allowed_load_calls': 0, 'in_title': True,
                         'busy': False, 'load_menu_busy': False, 'main_menu_busy': True}
                read_active_guard.return_value = guard
                with (patch('save_catalog.time.time', return_value=100),
                      self.assertRaisesRegex(ValueError, 'Slot 4 stimmt nicht')):
                    stage_campaign('scenario:4')

            bridge.side_effect = click
            mod.start(self.game, 'host', prepared_save_directory=self.save.parent)
            arm.assert_not_called()

    def test_loaded_campaign_compares_the_same_attempt_on_the_dedicated_pipe(self):
        from threading import Event

        data = self.game / 'reframework/data'
        policy = {'id': 'e' * 32, 'lobby_load': {'session_id': 'a' * 32, 'attempt_id': 'b' * 32,
                                               'guard_run_id': 'native-G', 'membership': {'revision': 17}}}
        report = {'scope': 'prepared_load_checkpoint', 'attempt_id': 'b' * 32,
                  'checkpoint_match': True, 'native_pause_match': True, 'resume_authorized': True}
        guard = {'protection': {'game_pid': 42}, 'load_hold': {'load_request_id': policy['id'], 'pause_id': policy['id'],
                 'guard_run_id': 'native-G', 'phase': 'released', 'native_phase': 'released'}}
        stop = Event()
        with (patch('readonly_save_control.wait_for_result') as wait,
              patch('readonly_save_control.read_active_guard', return_value=guard),
              patch('steam_pose_bridge.SteamPipe') as pipe,
              patch('save_protection.storage_guard_active', return_value=True) as acl,
              patch('save_protection.active_save_identity') as active_source,
              patch('prepared_checkpoint.PreparedCheckpoint.capture',
                    side_effect=[ValueError('native observer still updating'), {}]) as capture,
              patch('steam_snapshot_transfer.confirm_prepared_checkpoint', return_value=report) as compare):
            pipe.return_value.lobby_status.return_value = 'joined'
            pipe.return_value.cloud_status.return_value = 'cloud-app-disabled'
            pipe.return_value.membership_revision.return_value = 17
            pipe.return_value.epoch = b'epoch-01'
            mod._confirm_loaded_campaign(data, 42, b'G', policy, self.save.parent, stop)
            wait.assert_called_once_with(data, policy['id'], load=True, timeout=90, require_pause=True, stop=stop)
            pipe.assert_called_once_with(42, stream='snapshot')
            self.assertEqual(compare.call_args.args[0:2], (pipe.return_value, b'G'))
            self.assertEqual(compare.call_args.args[3:], ('a' * 32, 'b' * 32))
            self.assertEqual(compare.call_args.args[2].game_pid, 42)
            self.assertTrue(callable(compare.call_args.kwargs['resume']))
            self.assertIs(compare.call_args.kwargs['stop'], stop)
            acl.assert_called_once_with(self.save.parent)
            active_source.assert_called_once_with(pipe.return_value, self.save.parent)
            self.assertEqual(capture.call_count, 2)
            receipt = mod.read(data / 're2_coop_campaign_checkpoint.json')
            self.assertEqual((receipt['game_pid'], receipt['load_request_id']), (42, policy['id']))
            self.assertIs(receipt['checkpoint_match'], True)
            resume = mod.read(data / 're2_coop_campaign_resume.json')
            self.assertEqual(resume['load_request_id'], policy['id'])
            self.assertEqual(resume['lobby_load'], policy['lobby_load'])
            self.assertEqual(resume['snapshot_epoch'], b'epoch-01'.hex())

    def test_loaded_campaign_does_not_publish_a_different_attempt(self):
        from threading import Event

        data = self.game / 'reframework/data'
        policy = {'id': 'e' * 32, 'lobby_load': {'session_id': 'a' * 32, 'attempt_id': 'b' * 32}}
        stale = {'scope': 'prepared_load_checkpoint', 'attempt_id': 'c' * 32,
                 'checkpoint_match': True, 'native_pause_match': True}
        with (patch('readonly_save_control.wait_for_result'), patch('steam_pose_bridge.SteamPipe'),
              patch('prepared_checkpoint.PreparedCheckpoint.capture', return_value={}),
              patch('steam_snapshot_transfer.confirm_prepared_checkpoint', return_value=stale),
              redirect_stderr(io.StringIO())):
            mod._confirm_loaded_campaign(data, 42, b'H', policy, self.save.parent, Event())
        self.assertFalse((data / 're2_coop_campaign_checkpoint.json').exists())
        self.assertFalse((data / 're2_coop_campaign_resume.json').exists())

    def test_loaded_campaign_does_not_publish_resume_after_cloud_is_reenabled(self):
        from threading import Event

        data = self.game / 'reframework/data'
        policy = {'id': 'e' * 32, 'lobby_load': {'session_id': 'a' * 32, 'attempt_id': 'b' * 32,
                                               'membership': {'revision': 17}}}
        report = {'scope': 'prepared_load_checkpoint', 'attempt_id': 'b' * 32,
                  'checkpoint_match': True, 'native_pause_match': True, 'resume_authorized': True}
        with (patch('readonly_save_control.wait_for_result'),
              patch('steam_pose_bridge.SteamPipe') as pipe,
              patch('prepared_checkpoint.PreparedCheckpoint.capture', return_value={}),
              patch('steam_snapshot_transfer.confirm_prepared_checkpoint', return_value=report),
              redirect_stderr(io.StringIO()) as output):
            pipe.return_value.lobby_status.return_value = 'owned'
            pipe.return_value.membership_revision.return_value = 17
            pipe.return_value.cloud_status.return_value = 'cloud-enabled'
            mod._confirm_loaded_campaign(data, 42, b'H', policy, self.save.parent, Event())
        self.assertIn('Schutz fuer den Kampagnenstart nicht mehr aktiv', output.getvalue())
        self.assertFalse((data / 're2_coop_campaign_resume.json').exists())

    def prepared_starter_fixture(self, stack, *, wrong_directory=False, cloud='cloud-app-disabled', acl=True):
        locks = stack.enter_context(patch('save_file_guard.SaveFileLocks'))
        active_locks = locks.return_value.__enter__.return_value
        active_locks.locked_count = 1
        child = active_locks.spawn.return_value
        child.pid = 42
        child.poll.return_value = None
        stack.enter_context(patch.object(mod.secrets, 'token_hex', return_value='a' * 32))
        stack.enter_context(patch.object(mod, 'game_process', return_value={'pid': 42, 'started': 'fixture'}))
        stack.enter_context(patch.object(mod.threading, 'Thread'))
        stack.enter_context(patch('save_protection.read_save_protection', return_value={'game_pid': 42, 'run_id': 'a' * 32}))
        stack.enter_context(patch('readonly_save_control.read_active_guard', return_value={'protection_active': True}))
        stack.enter_context(patch('readonly_save_control._storage_guard_active', side_effect=[True, acl]))
        pipe = stack.enter_context(patch('steam_pose_bridge.SteamPipe')).return_value
        pipe.save_directory.return_value = self.save.parent.parent if wrong_directory else self.save.parent
        pipe.cloud_status.return_value = cloud
        pipe.lobby_status.return_value = 'idle'
        pipe.membership_revision.return_value = None
        bridge = stack.enter_context(patch('steam_pose_bridge.run_bridge'))
        return child, pipe, bridge

    def test_prepared_starter_refuses_wrong_directory_enabled_cloud_or_lost_acl(self):
        mod.install(self.game)
        faults = (({'wrong_directory': True}, 'active Steam save directory'),
                  ({'cloud': 'cloud-enabled'}, 'Steam Cloud'), ({'acl': False}, 'Windows-ACL'))
        for options, message in faults:
            with self.subTest(**options), ExitStack() as stack:
                child, _, bridge = self.prepared_starter_fixture(stack, **options)
                with self.assertRaisesRegex(ValueError, message):
                    mod.start(self.game, 'host', prepared_save_directory=self.save.parent)
                child.terminate.assert_called_once_with()
                bridge.assert_not_called()

    def test_load_rejects_missing_or_foreign_package_session(self):
        data, _ = self.ready_load()
        session = data / 're2_coop_test_session.json'
        for state in (None, {'active': True, 'id': 'b' * 32, 'game_pid': 42}):
            if state is None:
                session.unlink()
            else:
                self.real_write(session, state)
            with (patch.object(mod, 'game_process', return_value={'pid': 42}),
                  patch('readonly_save_control.time.time', return_value=100),
                  patch('readonly_save_control.wait_for_result'),
                  self.assertRaisesRegex(ValueError, 'Test-Bridge')):
                mod.load(self.game, 'scenario:4')
            self.assertFalse((data / 're2_coop_save_policy.json').exists())

    def prepared_load(self):
        from save_catalog import SaveCatalog
        from sync_model import state_digest
        data, _ = self.ready_load()
        path = self.save.parent / 'data004Slot.bin'
        path.write_bytes(b'disposable comparison fixture')
        self.real_write(data / 're2_coop_test_session.json', {'active': True, 'id': 'a' * 32,
            'game_pid': 42, 'prepared_save_directory': str(path.parent)})
        guard_path = data / 're2_coop_save_guard.json'
        self.real_write(guard_path, {**mod.read(guard_path), 'guard_run_id': 'native-run'})
        selection = SaveCatalog(data / 're2_coop_save_catalog.json', allow_date='2026-04-08')
        with patch('save_catalog.time.time', return_value=100):
            reference = selection.select('scenario:4')
        body = {'host_id': 'leon', 'guest_id': 'claire', 'revision': 7, 'connected': True,
                'ready': {'leon': True, 'claire': True}, 'settings': {}, 'save_slot': 'scenario:4',
                'save_ref': reference,
                'load_check': {'phase': 'prepared', 'revision': 7, 'reason': '', 'attempt_id': 'b' * 32, 'admission': 1,
                               'save_digest': hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.real_write(data / 're2_coop_lobby.json', {'schema': 1, 'written_at': 100, 'connected': True,
             'game_pid': 42, 'role': 'H', 'steam_lobby': 'owned',
             'steam_membership': {'session_id': 'c' * 32, 'revision': 9},
             'lobby': {'version': 1, 'type': 'lobby_state', 'session_id': 'lobby-session',
                       'sequence': 6, 'digest': state_digest(body), 'data': body}})
        return data

    def test_package_stages_the_load_and_waits_for_pause_in_prepared_session(self):
        data = self.prepared_load()
        with (patch.object(mod, 'game_process', return_value={'pid': 42}),
              patch('readonly_save_control.time.time', return_value=100),
              patch('readonly_save_control.SteamPipe') as pipe,
              patch('readonly_save_control._storage_guard_active', return_value=True),
              patch('readonly_save_control.wait_for_result') as wait):
            pipe.return_value.save_directory.return_value = self.save.parent
            pipe.return_value.lobby_status.return_value = 'owned'
            pipe.return_value.membership_revision.return_value = 9
            pipe.return_value.request.return_value = b'peer-ready'
            pipe.return_value.cloud_status.return_value = 'cloud-app-disabled'
            mod.load(self.game, 'scenario:4')
        policy = mod.read(data / 're2_coop_save_policy.json')
        self.assertEqual(policy['schema'], 3)
        self.assertEqual(policy['lobby_load']['attempt_id'], 'b' * 32)
        wait.assert_called_once_with(data, policy['id'], load=True, timeout=90, require_pause=True)

    def test_package_prepared_session_without_peer_cannot_fall_back_to_manual_load(self):
        data = self.prepared_load()
        (data / 're2_coop_lobby.json').unlink()
        with (patch.object(mod, 'game_process', return_value={'pid': 42}),
              patch('readonly_save_control.time.time', return_value=100),
              patch('readonly_save_control.wait_for_result'),
              self.assertRaises((OSError, ValueError))):
            mod.load(self.game, 'scenario:4')
        self.assertFalse((data / 're2_coop_save_policy.json').exists())
        self.assertFalse((data / 're2_coop_lobby_view.json').exists())

    def test_legacy_installation_keeps_the_original_date_filter(self):
        data, timestamp = self.ready_load(allow_save_date='2026-11-11', catalog_date='2026-11-11', legacy=True)
        with (patch.object(mod, 'game_process', return_value={'pid': 42}),
              patch('readonly_save_control.time.time', return_value=100),
              patch('readonly_save_control.wait_for_result')):
            mod.load(self.game, 'scenario:4')
        self.assertEqual(mod.read(data / 're2_coop_save_policy.json')['reference']['timestamp'], timestamp)
        self.assertEqual(mod.read(data / 're2_coop_test_load.json')['date'], '2026-11-11')

    def test_host_cannot_override_the_installation_date_on_the_command_line(self):
        errors = io.StringIO()
        with (patch.object(sys, 'argv', ['test_mod.py', 'host', '--allow-save-date', '2026-04-08']),
              patch.object(mod, 'find_game') as find, redirect_stderr(errors),
              self.assertRaises(SystemExit) as raised):
            mod.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn('nur bei install', errors.getvalue())
        find.assert_not_called()

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
    def test_save_inventory_rejects_a_directory_junction(self):
        import _winapi
        external = Path(self.temp.name) / 'external-saves'
        external.mkdir()
        (external / 'data999.bin').write_bytes(b'external fixture')
        user = next((self.steam / 'userdata').iterdir())
        link = user / '883710' / 'external'
        _winapi.CreateJunction(str(external), str(link))
        try:
            with self.assertRaisesRegex(ValueError, 'Verknuepfung'):
                mod.save_inventory()
        finally:
            link.rmdir()
        self.assertEqual((external / 'data999.bin').read_bytes(), b'external fixture')

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
