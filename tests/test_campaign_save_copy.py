import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from campaign_save_copy import check_managed_save, open_save_session


class CampaignSaveCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(TemporaryDirectory())
        self.app = Path(self.temp).resolve() / 'userdata' / '123456' / '883710'
        self.directory = self.app / 'remote' / 'win64_save'
        self.directory.mkdir(parents=True)
        self.save = self.directory / 'data000.bin'
        self.save.write_bytes(b'original save')
        (self.directory / 'empty.bin').touch()
        self.original = self.directory.stat().st_ino
        self.require_closed = Mock()

    def test_isolates_files_then_restores_the_original_directory(self):
        with open_save_session(self.directory, self.require_closed) as session:
            session.install()
            self.assertNotEqual(self.directory.stat().st_ino, self.original)
            self.assertEqual(self.save.read_bytes(), b'original save')
            self.assertEqual((self.directory / 'empty.bin').read_bytes(), b'')
            check_managed_save(self.directory)
            self.save.write_bytes(b'test checkpoint')
            retained = session.restore()

        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'original save')
        self.assertEqual((retained / self.save.name).read_bytes(), b'test checkpoint')
        check_managed_save(self.directory)
        with open_save_session(self.directory, self.require_closed) as session:
            self.assertIsNone(session.restore())
            session.install()
            self.assertNotEqual(session.restore(), retained)

    def test_recovers_after_interrupt_between_original_backup_and_copy_install(self):
        script = """
import os
from pathlib import Path
import sys
from campaign_save_copy import open_save_session

directory = Path(sys.argv[1])
move = os.rename

def interrupt(source, target):
    if target == directory:
        os._exit(42)
    move(source, target)

with open_save_session(directory, lambda: None) as session:
    os.rename = interrupt
    session.install()
"""
        child = subprocess.run([sys.executable, '-B', '-c', script, str(self.directory)],
                               cwd=Path(__file__).resolve().parents[1], timeout=20)
        self.assertEqual(child.returncode, 42)
        self.assertFalse(self.directory.exists())
        with open_save_session(self.directory, self.require_closed) as session:
            retained = session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual((retained / self.save.name).read_bytes(), b'original save')

    def test_recovers_after_interrupt_between_copy_removal_and_original_restore(self):
        move = os.rename
        with open_save_session(self.directory, self.require_closed) as session:
            session.install()
            self.save.write_bytes(b'test checkpoint')

            def interrupted(source, target):
                if target == self.directory:
                    raise KeyboardInterrupt
                return move(source, target)

            with patch('campaign_save_copy.os.rename', side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    session.restore()

        self.assertFalse(self.directory.exists())
        with open_save_session(self.directory, self.require_closed) as session:
            retained = session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual((retained / self.save.name).read_bytes(), b'test checkpoint')

    def test_refuses_foreign_replacement_and_keeps_the_recovery_record(self):
        with open_save_session(self.directory, self.require_closed) as session:
            session.install()
            displaced = self.directory.with_name('displaced')
            self.directory.rename(displaced)
            self.directory.mkdir()
            self.save.write_bytes(b'unexpected local save')
            with self.assertRaises(ValueError):
                check_managed_save(self.directory)
            with self.assertRaises(ValueError):
                session.restore()
            with self.assertRaises(ValueError):
                session.install()
            self.assertEqual(self.save.read_bytes(), b'unexpected local save')
            self.save.unlink()
            self.directory.rmdir()
            displaced.rename(self.directory)
            session.restore()
        self.assertEqual(self.save.read_bytes(), b'original save')

    def test_refuses_changed_source_without_switching(self):
        def change_source_before_install():
            if self.require_closed.call_count == 2:
                self.save.write_bytes(b'new original checkpoint')

        self.require_closed.side_effect = change_source_before_install
        with open_save_session(self.directory, self.require_closed) as session:
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                session.install()
            self.assertIsNone(session.restore())
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'new original checkpoint')

    def test_refuses_install_or_restore_while_game_is_running(self):
        with open_save_session(self.directory, self.require_closed) as session:
            self.require_closed.side_effect = ValueError('RE2 is running')
            with self.assertRaisesRegex(ValueError, 'RE2 is running'):
                session.install()
            self.assertEqual(self.directory.stat().st_ino, self.original)
            self.require_closed.side_effect = None
            session.install()
            copy_id = self.directory.stat().st_ino
            self.require_closed.side_effect = ValueError('RE2 is running')
            with self.assertRaisesRegex(ValueError, 'RE2 is running'):
                session.restore()
            self.assertEqual(self.directory.stat().st_ino, copy_id)
            self.require_closed.side_effect = None
            session.restore()

    def test_refuses_concurrent_sessions(self):
        with open_save_session(self.directory, self.require_closed):
            with self.assertRaises(ValueError):
                with open_save_session(self.directory, self.require_closed):
                    self.fail('Concurrent session opened')

    @unittest.skipUnless(sys.platform == 'win32', 'requires the Windows guard record path')
    def test_waits_for_acl_recovery_before_moving_either_directory(self):
        from save_protection import _storage_guard_record

        local = self.app.parent / 'local'
        with patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
            journal = _storage_guard_record(self.directory, '.json')
            journal.parent.mkdir(parents=True)
            with open_save_session(self.directory, self.require_closed) as session:
                journal.write_text('pending ACL recovery')
                with self.assertRaisesRegex(ValueError, 'access rules'):
                    session.install()
                self.assertEqual(self.directory.stat().st_ino, self.original)
                journal.unlink()
                session.install()
                copy_id = self.directory.stat().st_ino
                journal.write_text('pending ACL recovery')
                with self.assertRaisesRegex(ValueError, 'access rules'):
                    session.restore()
                self.assertEqual(self.directory.stat().st_ino, copy_id)
                journal.unlink()
                session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)

    def test_refuses_nested_and_hard_linked_files(self):
        extra = self.directory / 'unexpected'
        extra.mkdir()
        with open_save_session(self.directory, self.require_closed) as session:
            with self.assertRaises(ValueError):
                session.install()
            extra.rmdir()
            os.link(self.save, extra)
            with self.assertRaises(ValueError):
                session.install()
        self.assertEqual(self.directory.stat().st_ino, self.original)

    def test_refuses_other_app_and_noncanonical_paths(self):
        for directory in (self.app.with_name('0') / 'remote/win64_save',
                          self.directory.parent / '..' / 'remote/win64_save',
                          Path('userdata/123456/883710/remote/win64_save')):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                with open_save_session(directory, self.require_closed):
                    self.fail('Invalid path accepted')

    @unittest.skipUnless(sys.platform == 'win32', 'requires Windows NTFS and PowerShell')
    def test_stock_windows_acl_guard_protects_the_active_copy(self):
        root = Path(__file__).resolve().parents[1]
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        probe = r"""
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from campaign_save_copy import check_managed_save
from save_protection import storage_guard_active

directory = Path(sys.argv[2])
check_managed_save(directory)
assert storage_guard_active(directory)
existing = directory / 'data000.bin'
assert existing.read_bytes() == b'original save'
for target in (existing, directory / 'new.bin'):
    try:
        target.write_bytes(b'unexpected checkpoint')
    except PermissionError:
        continue
    raise AssertionError(f'Windows allowed a write to {target.name}')
"""
        env = {**os.environ, 'RE2_TEST_COPY': str(self.directory),
               'RE2_TEST_WRAPPER': str(root / 'bridge/scripts/protect_re2_test_saves.ps1'),
               'RE2_TEST_SOURCE': str(root / 'bridge'), 'RE2_TEST_PYTHON': sys.executable, 'RE2_TEST_PROBE': probe}
        env['PSModulePath'] = str(powershell.parent / 'Modules')
        with open_save_session(self.directory, self.require_closed) as session:
            session.install()
            try:
                child = subprocess.run(
                    [str(powershell), '-NoProfile', '-NonInteractive', '-Command',
                     "$ErrorActionPreference = 'Stop'; "
                     "& $env:RE2_TEST_WRAPPER -SaveDirectory $env:RE2_TEST_COPY -WhileProtected { "
                     "& $env:RE2_TEST_PYTHON -B -c $env:RE2_TEST_PROBE $env:RE2_TEST_SOURCE $env:RE2_TEST_COPY; "
                     "if ($LASTEXITCODE -ne 0) { throw 'Guarded copy failed its cross-process checks' } }"],
                    capture_output=True, env=env, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(child.returncode, 0, child.stderr.decode(errors='replace'))
            finally:
                retained = session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)
        self.assertEqual(self.save.read_bytes(), b'original save')
        self.assertEqual((retained / self.save.name).read_bytes(), b'original save')

    @unittest.skipUnless(sys.platform == 'win32', 'requires process handles and NTFS')
    def test_guard_acquires_and_restores_around_an_already_running_process(self):
        from campaign_setup import _guard_command
        from save_protection import storage_guard_active

        game = Path(self.temp).resolve() / f'coop-direct-{os.getpid()}.exe'
        shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/cmd.exe', game)
        command, env = _guard_command(self.directory)
        child = subprocess.Popen([str(game), '/d', '/c', 'pause'], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            guard = subprocess.Popen([*command, '-GameExecutable', str(game), '-GameProcessId', str(child.pid)],
                                     env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 15
                while not storage_guard_active(self.directory) and time.monotonic() < deadline and guard.poll() is None:
                    time.sleep(0.1)
                self.assertTrue(storage_guard_active(self.directory))
                with self.assertRaises(PermissionError):
                    self.save.write_bytes(b'private write')
            finally:
                child.communicate(input=b'q\n', timeout=8)
                self.assertEqual(guard.wait(timeout=15), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
        self.assertFalse(storage_guard_active(self.directory))
        self.assertEqual(self.save.read_bytes(), b'original save')
        self.save.write_bytes(b'restored')

    @unittest.skipUnless(sys.platform == 'win32', 'requires process handles and NTFS')
    def test_game_supervision_keeps_guard_until_the_exact_process_exits(self):
        from save_protection import storage_guard_active

        home = Path(self.temp).resolve()
        ready = home / 'guard-ready'
        system = Path(os.environ['SystemRoot']) / 'System32'
        powershell = system / 'WindowsPowerShell/v1.0/powershell.exe'
        # Keep a local fixture alive with stdin while the independent guard waits.
        game = home / f'game-fixture-{os.getpid()}.exe'
        shutil.copyfile(system / 'cmd.exe', game)
        script = Path(__file__).resolve().parents[1] / 'bridge/scripts/protect_re2_test_saves.ps1'
        env = {**os.environ, 'PSModulePath': str(powershell.parent / 'Modules')}
        with open_save_session(self.directory, self.require_closed) as session:
            session.install()
            guard = subprocess.Popen(
                [str(powershell), '-NoProfile', '-NonInteractive', '-File', str(script),
                 '-SaveDirectory', str(self.directory), '-GameExecutable', str(game),
                 '-ReadyFile', str(ready), '-LaunchTimeoutSeconds', '5'],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                deadline = time.monotonic() + 8
                while not ready.is_file() and guard.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                if guard.poll() is not None:
                    self.fail(guard.communicate(timeout=8)[0].decode(errors='replace'))
                self.assertTrue(ready.is_file())
                self.assertTrue(storage_guard_active(self.directory))
                game_process = subprocess.Popen([str(game), '/d', '/c', 'pause'], stdin=subprocess.PIPE,
                                                stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        guard.wait(timeout=5.2)
                    self.assertIsNone(game_process.poll())
                    self.assertTrue(storage_guard_active(self.directory))
                    with self.assertRaises(PermissionError):
                        self.save.write_bytes(b'unexpected checkpoint')
                finally:
                    try:
                        game_process.communicate(input=b'q\n', timeout=8)
                    finally:
                        if game_process.poll() is None:
                            game_process.kill()
                            game_process.communicate(timeout=8)
                output, _ = guard.communicate(timeout=8)
                self.assertEqual(guard.returncode, 0, output.decode(errors='replace'))
            finally:
                if guard.poll() is None:
                    guard.kill()
                guard.communicate(timeout=8)
            self.assertFalse(storage_guard_active(self.directory))
            session.restore()
        self.assertEqual(self.directory.stat().st_ino, self.original)
