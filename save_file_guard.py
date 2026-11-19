"""Windows read-sharing locks for existing test save files; no save writes or ACL changes."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess


class SaveFileLocks:
    """Deny write/delete opens until close; shared reads remain available.

    Before a protected run, pin the locks into the verified owned game child
    or ensure this owner outlives RE2 even if the bridge exits. This class
    alone does not launch or supervise a game or a Steam forwarding process.
    """

    def __init__(self, files):
        if os.name != 'nt':
            raise OSError('save file sharing locks require Windows')
        self.paths = tuple(dict.fromkeys(Path(path).resolve(strict=True) for path in files))
        if not self.paths:
            raise ValueError('expected at least one protected file')
        self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self._kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self._kernel.CreateFileW.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self._kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                                wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
                                                wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.DuplicateHandle.restype = wintypes.BOOL
        self._kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self._kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._handles = []
        self._retained = set()

    def __enter__(self):
        if self._handles:
            raise ValueError('save file locks already acquired')
        try:
            for path in self.paths:
                if not path.is_file():
                    raise ValueError('protected path must be an existing regular file')
                # Desired access 0 / FILE_READ_ATTRIBUTES do not block writers.
                handle = self._kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._handles.append(handle)
            return self
        except BaseException:
            self.close()
            raise

    @property
    def locked_count(self):
        return len(self._handles)

    def retain_in_process(self, process, expected_executable):
        """Pin locks in an owned Popen child until it exits, even if this owner dies.

        This is irreversible while the child runs. Only pass the actual game
        process, never a Steam forwarding process. No process is started here.
        The original process handle prevents a PID-reuse race.
        """
        if len(self._handles) != len(self.paths):
            raise ValueError('all file locks must be acquired first')
        if not isinstance(process, subprocess.Popen):
            raise TypeError('expected an owned subprocess.Popen child')
        handle = int(process._handle)
        if self._kernel.WaitForSingleObject(handle, 0) != 258:
            raise ValueError('owned child is not running')
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        if not self._kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        expected = Path(expected_executable).resolve(strict=True)
        if os.path.normcase(str(Path(image.value).resolve(strict=True))) != os.path.normcase(str(expected)):
            raise ValueError('owned child executable does not match')
        if process in self._retained:
            raise ValueError('locks already retained in this child')
        current = self._kernel.GetCurrentProcess()
        copied = []
        try:
            for source in self._handles:
                target = wintypes.HANDLE()
                if not self._kernel.DuplicateHandle(current, source, handle, ctypes.byref(target), 0, False, 2):
                    raise ctypes.WinError(ctypes.get_last_error())
                copied.append(target.value)
            if self._kernel.WaitForSingleObject(handle, 0) != 258:
                raise ValueError('owned child exited during retention')
        except BaseException:
            # Reclaim partial copies, keeping our original locks held. If the
            # child already exited Windows has closed its copies instead.
            for target in copied:
                reclaimed = wintypes.HANDLE()
                if self._kernel.DuplicateHandle(handle, target, current, ctypes.byref(reclaimed), 0, False, 3):
                    self._kernel.CloseHandle(reclaimed)
            raise
        self._retained.add(process)
        return len(copied)

    def spawn(self, executable, arguments=(), *, cwd=None, env=None):
        """Start the real owned executable with locks inherited at process creation.

        Never use Steam or another forwarding executable here. Parent exit
        cannot release the child's handles, including before its first instruction.
        """
        if len(self._handles) != len(self.paths):
            raise ValueError('all file locks must be acquired before launch')
        executable = Path(executable).resolve(strict=True)
        if not executable.is_file():
            raise ValueError('expected an executable file')
        current = self._kernel.GetCurrentProcess()
        inherited = []
        try:
            for source in self._handles:
                duplicate = wintypes.HANDLE()
                if not self._kernel.DuplicateHandle(current, source, current, ctypes.byref(duplicate), 0, True, 2):
                    raise ctypes.WinError(ctypes.get_last_error())
                inherited.append(duplicate.value)
            startup = subprocess.STARTUPINFO(lpAttributeList={'handle_list': inherited})
            return subprocess.Popen([str(executable), *arguments], cwd=cwd, env=env,
                                    startupinfo=startup, close_fds=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                                   | subprocess.CREATE_NO_WINDOW))
        finally:
            for handle in inherited:
                self._kernel.CloseHandle(handle)

    def close(self):
        for handle in reversed(self._handles):
            self._kernel.CloseHandle(handle)
        self._handles.clear()

    def __exit__(self, *_):
        self.close()
