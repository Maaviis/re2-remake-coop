import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from campaign_save_copy import open_save_session
from campaign_setup import CampaignSetup, STATUS, _guard_command, _restore_access, _supervise_game, require_steam_save, run_campaign_copy
from lobby_sync import write_json
from save_protection import storage_guard_active, storage_guard_recovery_pending


class CampaignSetupTests(unittest.TestCase):
    def setUp(self):
        home = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.directory = home / 'userdata/123/883710/remote/win64_save'
        self.directory.mkdir(parents=True)
        self.save = self.directory / 'data000Slot.bin'
        self.save.write_bytes(b'original')
        self.original = self.directory.stat().st_ino

    def test_protects_only_the_copy_and_restores_after_the_game_returns(self):
        def guarded_game(ready):
            self.assertFalse(ready.exists())
            self.assertNotEqual(self.directory.stat().st_ino, self.original)
            self.assertEqual(self.save.read_bytes(), b'original')
            self.save.write_bytes(b'game checkpoint')

        run_campaign_copy(self.directory, Mock(), guarded_game, Mock())
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'original')

    def test_failed_launch_restores_preserved_original(self):
        launch = Mock(side_effect=OSError('Steam did not start'))
        with self.assertRaisesRegex(OSError, 'Steam did not start'):
            run_campaign_copy(self.directory, Mock(), launch, Mock())
        launch.assert_called_once()
        self.assertEqual(self.directory.stat().st_ino, self.original)

    def test_refuses_unbound_acl_recovery(self):
        restore_acl, launch = Mock(), Mock()
        with patch('campaign_setup.storage_guard_recovery_pending', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Spielstandkopie'):
                run_campaign_copy(self.directory, Mock(), launch, restore_acl)
        restore_acl.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(self.directory.stat().st_ino, self.original)

    def test_cloud_or_a_different_steam_account_blocks_the_copy(self):
        pipe = Mock()
        pipe.save_directory.return_value = self.directory
        pipe.cloud_status.return_value = 'cloud-enabled'
        with self.assertRaisesRegex(ValueError, 'Steam Cloud'):
            require_steam_save(pipe)
        pipe.cloud_status.return_value = 'cloud-app-disabled'
        self.assertEqual(require_steam_save(pipe), self.directory)
        with self.assertRaisesRegex(ValueError, 'Steam-Konto'):
            require_steam_save(pipe, self.directory.with_name('different'))

    def test_menu_schedules_once_then_arms_only_from_a_live_guard(self):
        game = Mock(_handle=79)
        pipe = Mock()
        pipe.save_directory.return_value = self.directory
        pipe.cloud_status.return_value = 'cloud-account-disabled'
        package = self.directory.parent
        setup = CampaignSetup(package, pipe, game)
        with (patch('campaign_setup.PACKAGE', package),
              patch('campaign_setup.start_setup') as start,
              patch('campaign_setup.storage_guard_active', return_value=False) as active,
              patch('campaign_start.prepare_runtime_campaign') as prepare):
            start.return_value.poll.return_value = None
            self.assertIsNone(setup.enable())
            self.assertEqual(setup.status(), ('closing', None))
            with self.assertRaisesRegex(ValueError, 'schliessen'):
                setup.enable()
            start.assert_called_once_with(package, pipe, 79)
            prepare.assert_not_called()

            after_restart = CampaignSetup(package, pipe, game)
            active.return_value = True
            self.assertEqual(after_restart.enable(), prepare.return_value)
            prepare.assert_called_once_with(package, pipe, None, game)

    def test_failed_helper_reports_its_own_reason_and_allows_retry(self):
        data = self.directory.parent
        reason = 'Steam Cloud wurde waehrend der Vorbereitung aktiviert.'
        report = {'schema': 1, 'phase': 'failed', 'at': int(time.time()), 'helper_pid': 42, 'error': reason}
        write_json(data / STATUS, report)
        pipe = Mock()
        pipe.save_directory.return_value = self.directory
        pipe.cloud_status.return_value = 'cloud-app-disabled'
        setup = CampaignSetup(data, pipe, Mock())
        self.assertEqual(setup.status(), ('failed', reason))

        first = Mock(pid=43)
        first.poll.return_value = 1
        second = Mock(pid=44)
        second.poll.return_value = None
        with (patch('campaign_setup.storage_guard_active', return_value=False),
              patch('campaign_setup.start_setup', side_effect=[first, second])):
            setup.enable()
            self.assertEqual(setup.status(), ('failed', None), 'older helper failure must not be repeated')
            setup.enable()
            self.assertEqual(setup.status(), ('closing', None))
            write_json(data / STATUS, {**report, 'helper_pid': second.pid})
            second.poll.return_value = 1
            self.assertEqual(setup.status(), ('failed', reason))

    def test_startup_ignores_expired_or_unprintable_failure_detail(self):
        data = self.directory.parent
        report = {'schema': 1, 'phase': 'failed', 'at': int(time.time()), 'error': 'bad\nformat'}
        write_json(data / STATUS, report)
        self.assertEqual(CampaignSetup(data, Mock(), Mock()).status(), ('failed', None))
        write_json(data / STATUS, {**report, 'at': report['at'] - 301})
        self.assertEqual(CampaignSetup(data, Mock(), Mock()).status(), (None, None))

    @unittest.skipUnless(sys.platform == 'win32', 'requires the packaged Windows save guard')
    def test_handoff_starts_the_game_only_after_acl_protection_and_restores_on_exit(self):
        fixture = self.directory.parents[4]
        system = Path(os.environ['SystemRoot']) / 'System32'
        game = fixture / f'campaign-fixture-{os.getpid()}.exe'
        shutil.copyfile(system / 'ping.exe', game)
        steam = fixture / 'steam.exe'
        child = None
        popen = subprocess.Popen

        def launch(args, **kwargs):
            nonlocal child
            if args[0] != str(steam):
                return popen(args, **kwargs)
            self.assertEqual(args[1:], ['-applaunch', '883710'])
            self.assertTrue(storage_guard_active(self.directory))
            self.assertNotEqual(self.directory.stat().st_ino, self.original)
            self.assertEqual(self.save.read_bytes(), b'original')
            with self.assertRaises(PermissionError):
                self.save.write_bytes(b'unexpected')
            child = popen([str(game), '-n', '3', '127.0.0.1'], stdout=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW)
            return child

        with (patch('campaign_setup.subprocess.Popen', side_effect=launch),
              patch('campaign_setup._require_game_closed')):
            run_campaign_copy(self.directory, Mock(),
                              lambda ready: _supervise_game(self.directory, ready, game, steam), Mock())
        self.assertIsNotNone(child)
        self.assertEqual(child.poll(), 0)
        self.assertFalse(storage_guard_active(self.directory))
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'original')

    @unittest.skipUnless(sys.platform == 'win32', 'requires a durable Windows ACL journal')
    def test_pending_steam_launch_cannot_expose_original_at_timeout(self):
        fixture = self.directory.parents[4]
        system = Path(os.environ['SystemRoot']) / 'System32'
        game = fixture / f'late-campaign-fixture-{os.getpid()}.exe'
        shutil.copyfile(system / 'ping.exe', game)

        def timeout(ready):
            command, env = _guard_command(self.directory)
            result = subprocess.run([*command, '-GameExecutable', str(game), '-ReadyFile', str(ready),
                                     '-LaunchTimeoutSeconds', '1', '-PreserveOnLaunchTimeout'],
                                    env=env, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(ready.is_file(), result.stderr.decode(errors='replace'))
            self.assertTrue(storage_guard_recovery_pending(self.directory))
            self.assertFalse(storage_guard_active(self.directory))
            with self.assertRaises(PermissionError):
                self.save.write_bytes(b'unexpected')

        try:
            with self.assertRaisesRegex(ValueError, 'access rules'):
                run_campaign_copy(self.directory, Mock(), timeout, Mock())
            self.assertNotEqual(self.directory.stat().st_ino, self.original)
            late = subprocess.run([str(game), '-n', '1', '127.0.0.1'], stdout=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            self.assertEqual(late.returncode, 0)
            self.assertNotEqual(self.directory.stat().st_ino, self.original)
        finally:
            if storage_guard_recovery_pending(self.directory):
                _restore_access(self.directory)
            with open_save_session(self.directory, Mock()) as session:
                session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'original')
