import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from save_file_guard import SaveFileLocks


@unittest.skipUnless(os.name == 'nt', 'native Windows file sharing required')
class SaveFileLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.save = self.root / 'synthetic-save.bin'
        self.original = b'synthetic original save bytes'
        self.save.write_bytes(self.original)

    def test_shared_reads_work_but_truncate_replace_and_delete_are_denied(self):
        replacement = self.root / 'replacement.tmp'
        replacement.write_bytes(b'replacement fixture')
        with SaveFileLocks([self.save]) as locks:
            self.assertEqual(locks.locked_count, 1)
            self.assertEqual(self.save.read_bytes(), self.original)
            with self.assertRaises(PermissionError):
                self.save.write_bytes(b'checkpoint header without payload')
            with self.assertRaises(PermissionError):
                os.replace(replacement, self.save)
            with self.assertRaises(PermissionError):
                self.save.unlink()
            self.assertEqual(self.save.read_bytes(), self.original)
        self.save.write_bytes(b'after protection fixture')
        self.assertEqual(self.save.read_bytes(), b'after protection fixture')

    def test_another_process_cannot_write_the_protected_file(self):
        code = ('from pathlib import Path; import sys; '
                'p=Path(sys.argv[1]); p.write_bytes(b"other process fixture")')
        with SaveFileLocks([self.save]):
            result = subprocess.run([sys.executable, '-B', '-c', code, str(self.save)],
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'PermissionError', result.stderr)
            self.assertEqual(self.save.read_bytes(), self.original)

    def test_late_acquisition_failure_releases_earlier_handles(self):
        directory = self.root / 'not-a-save'
        directory.mkdir()
        locks = SaveFileLocks([self.save, directory])
        with self.assertRaises(ValueError):
            locks.__enter__()
        self.assertEqual(locks.locked_count, 0)
        self.save.write_bytes(b'no leaked file lock')
        self.assertEqual(self.save.read_bytes(), b'no leaked file lock')

    def test_pinned_locks_survive_owner_close_until_owned_child_exits(self):
        code = '''from pathlib import Path
import sys
sys.stdin.readline()
try:
    Path(sys.argv[1]).write_bytes(b'child write fixture')
except PermissionError:
    print('write denied', flush=True)
else:
    raise SystemExit('write unexpectedly succeeded')
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.save)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with SaveFileLocks([self.save]) as locks:
                self.assertEqual(locks.retain_in_process(child, sys.executable), 1)
                with self.assertRaises(ValueError):
                    locks.retain_in_process(child, sys.executable)
            self.assertEqual(locks.locked_count, 0)
            with self.assertRaises(PermissionError):
                self.save.write_bytes(b'owner no longer holds its handles')
            out, err = child.communicate('go\n', timeout=10)
            self.assertEqual(child.returncode, 0, err)
            self.assertEqual(out.strip(), 'write denied')
            self.assertEqual(self.save.read_bytes(), self.original)
            self.save.write_bytes(b'child exit releases retained handles')
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)

    def test_pinning_rejects_wrong_executable_and_exited_child(self):
        child = subprocess.Popen([sys.executable, '-B', '-c', 'import sys; sys.stdin.read()'],
                                 stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with SaveFileLocks([self.save]) as locks:
                with self.assertRaises(ValueError):
                    locks.retain_in_process(child, self.save)
                child.communicate(timeout=10)
                with self.assertRaises(ValueError):
                    locks.retain_in_process(child, sys.executable)
            self.save.write_bytes(b'no unintended retained handle')
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)

    def test_spawned_locks_survive_an_abrupt_owner_process_exit(self):
        import _winapi

        gate = self.root / 'child-exit-gate'
        child_code = '''from pathlib import Path
import sys, time
deadline = time.monotonic() + 15
while not Path(sys.argv[1]).exists() and time.monotonic() < deadline:
    time.sleep(0.01)
'''
        holder_code = '''import os, subprocess, sys
from save_file_guard import SaveFileLocks
with SaveFileLocks([sys.argv[1]]) as locks:
    child = locks.spawn(sys.executable, ['-B', '-c', sys.argv[3], sys.argv[2]])
    print(child.pid, flush=True)
    os._exit(23)
'''
        try:
            holder = subprocess.run([sys.executable, '-B', '-c', holder_code,
                                     str(self.save), str(gate), child_code],
                                    cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=10,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(holder.returncode, 23, holder.stderr)
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, int(holder.stdout.strip()))
            try:
                self.assertEqual(_winapi.WaitForSingleObject(handle, 0), 258)
                with self.assertRaises(PermissionError):
                    self.save.write_bytes(b'owner process no longer exists')
                self.assertEqual(self.save.read_bytes(), self.original)
                gate.write_text('exit', encoding='ascii')
                self.assertEqual(_winapi.WaitForSingleObject(handle, 10000), 0)
            finally:
                _winapi.CloseHandle(handle)
            self.save.write_bytes(b'game child exit releases its locks')
        finally:
            gate.touch(exist_ok=True)

    def test_spawn_inherits_locks_before_the_first_child_write(self):
        code = '''from pathlib import Path
import sys
try:
    Path(sys.argv[1]).write_bytes(b'first child instruction fixture')
except PermissionError:
    Path(sys.argv[2]).write_text('blocked', encoding='ascii')
else:
    raise SystemExit(1)
'''
        report = self.root / 'spawn-result.txt'
        with SaveFileLocks([self.save]) as locks:
            child = locks.spawn(sys.executable, ['-B', '-c', code, str(self.save), str(report)])
        try:
            self.assertEqual(child.wait(timeout=10), 0)
            self.assertEqual(report.read_text(encoding='ascii'), 'blocked')
            self.assertEqual(self.save.read_bytes(), self.original)
            self.save.write_bytes(b'child released its inherited locks')
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)

    def test_spawn_failure_closes_temporary_inheritable_handles(self):
        with SaveFileLocks([self.save]) as locks:
            with self.assertRaises(OSError):
                locks.spawn(self.save)  # Existing bytes are not a valid Windows executable.
            self.assertEqual(locks.locked_count, 1)
        self.save.write_bytes(b'no temporary inherited handle leaked')
