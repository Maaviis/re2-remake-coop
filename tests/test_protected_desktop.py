"""Windows background launch keeps desktop input and inherited save locks separate."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from save_file_guard import SaveFileLocks
from tools.test_package.protected_desktop import BackgroundDesktop


_WINDOW_FIXTURE = r"""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import sys
import time

user = ctypes.WinDLL('user32', use_last_error=True)
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
user.GetThreadDesktop.argtypes = [w.DWORD]
user.GetThreadDesktop.restype = w.HANDLE
user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
name = ctypes.create_unicode_buffer(256)
needed = w.DWORD()
desktop = user.GetThreadDesktop(kernel.GetCurrentThreadId())
assert user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
assert name.value == sys.argv[1]
user.CreateWindowExW.argtypes = [
    w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
]
user.CreateWindowExW.restype = w.HWND
window = user.CreateWindowExW(0, 'STATIC', 'Protected desktop fixture', 0xcf0000,
                              40, 40, 240, 130, None, None, None, None)
assert window
user.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user.ShowWindow(window, 5)

target, ready, go, report = map(Path, sys.argv[2:6])
ready.touch()
deadline = time.monotonic() + 8
while not go.exists() and time.monotonic() < deadline:
    time.sleep(.025)
assert go.exists()
locked = False
try:
    with target.open('ab') as stream:
        stream.write(b'blocked')
except PermissionError:
    locked = True
report.write_text(json.dumps({'private_window': True, 'inherited_file_lock': locked}), encoding='utf-8')
"""


@unittest.skipUnless(sys.platform == 'win32', 'requires Win32 desktops and file sharing')
class ProtectedDesktopTests(unittest.TestCase):
    def test_window_stays_on_private_desktop_and_owns_save_lock(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed, ready, go, report = (root / name for name in ('seed', 'ready', 'go', 'report.json'))
            seed.write_bytes(b'unchanged')
            with BackgroundDesktop() as desktop:
                with SaveFileLocks([seed]) as locks:
                    child = desktop.spawn(locks, sys.executable, [
                        '-B', '-c', _WINDOW_FIXTURE, desktop.name,
                        *(str(path) for path in (seed, ready, go, report)),
                    ])
                deadline = time.monotonic() + 6
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(.025)
                self.assertTrue(ready.exists())
                self.assertTrue(desktop.has_window_for(child))
                desktop.check_input_isolation()
                go.touch()
                self.assertEqual(child.wait(timeout=10), 0)
                desktop.check_input_isolation()
            self.assertEqual(json.loads(report.read_text(encoding='utf-8')),
                             {'private_window': True, 'inherited_file_lock': True})
            self.assertEqual(seed.read_bytes(), b'unchanged')
