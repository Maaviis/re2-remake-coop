"""Create an input-isolated Windows desktop for a protected game test."""

import ctypes
from ctypes import wintypes as w
from pathlib import Path
from queue import Queue
import secrets
import subprocess
from threading import Thread


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
        ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD), ('x_count', w.DWORD),
        ('y_count', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD), ('show', w.WORD), ('reserved_count', w.WORD),
        ('reserved_bytes', w.LPVOID), ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [('startup', _StartupInfo), ('attributes', w.LPVOID)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class _Child:
    def __init__(self, kernel, result, command):
        self.kernel, self.handle, self.pid, self.command = kernel, result.process, result.pid, command

    def _wait(self, millis):
        status = self.kernel.WaitForSingleObject(self.handle, millis)
        if status == 258:
            return None
        code = w.DWORD()
        if status != 0 or not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def poll(self):
        return self._wait(0)

    def wait(self, timeout=None):
        result = self._wait(0xffffffff if timeout is None else max(0, int(timeout*1000)))
        if result is None:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return result

    def terminate(self):
        if self.poll() is None and not self.kernel.TerminateProcess(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())


class BackgroundDesktop:
    def __init__(self):
        self.name = 'RE2CoopTest-' + secrets.token_hex(8)
        self.handle = None
        self.child = None
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]
        self.user.CreateDesktopW.restype = w.HANDLE
        self.user.CloseDesktop.argtypes = [w.HANDLE]
        self.user.CloseDesktop.restype = w.BOOL
        self.user.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.user.OpenInputDesktop.restype = w.HANDLE
        self.user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD,
                                                        ctypes.POINTER(w.DWORD)]
        self.user.GetUserObjectInformationW.restype = w.BOOL
        self.user.GetProcessWindowStation.restype = w.HANDLE
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        self._enum_callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.user.EnumDesktopWindows.argtypes = [w.HANDLE, self._enum_callback, w.LPARAM]
        self.user.EnumDesktopWindows.restype = w.BOOL
        self.kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.kernel.WaitForSingleObject.restype = w.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        self.kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.InitializeProcThreadAttributeList.argtypes = [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.UpdateProcThreadAttribute.argtypes = [
            w.LPVOID, w.DWORD, ctypes.c_size_t, w.LPVOID, ctypes.c_size_t, w.LPVOID, w.LPVOID,
        ]
        self.kernel.DeleteProcThreadAttributeList.argtypes = [w.LPVOID]
        self.kernel.CreateProcessW.argtypes = [
            w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD, w.LPVOID, w.LPCWSTR,
            ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo),
        ]

    def __enter__(self):
        result = Queue()

        def create():
            # Use a transient thread so the terminal never adopts the test desktop.
            access = 0x200cf  # object access, window creation and hooks on this desktop
            handle = self.user.CreateDesktopW(self.name, None, None, 0, access, None)
            result.put((handle, ctypes.get_last_error()))

        thread = Thread(target = create)
        thread.start()
        thread.join()
        self.handle, error = result.get_nowait()
        if not self.handle:
            raise ctypes.WinError(error)
        try:
            self.check_input_isolation()
        except BaseException:
            self.__exit__()
            raise
        return self

    def check_input_isolation(self):
        live = self.user.OpenInputDesktop(0, False, 0x0001)
        if not live:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.object_name(live).casefold() == self.name.casefold():
                raise RuntimeError('test desktop is receiving input; protected test stopped')
        finally:
            self.user.CloseDesktop(live)

    def object_name(self, handle):
        name = ctypes.create_unicode_buffer(256)
        needed = w.DWORD()
        if not self.user.GetUserObjectInformationW(handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return name.value

    def has_window_for(self, child):
        if self.child is not child or child.poll() is not None:
            return False
        found = []

        @self._enum_callback
        def visit(window, _):
            pid = w.DWORD()
            if self.user.GetWindowThreadProcessId(window, ctypes.byref(pid)) and pid.value == child.pid:
                found.append(True)
            return True
        self.user.EnumDesktopWindows(self.handle, visit, 0)
        return bool(found)

    def spawn(self, locks, executable, arguments=(), *, cwd=None, env=None):
        self.check_input_isolation()
        if not self.handle or self.child is not None or not locks.locked_count or locks.locked_count != len(locks.paths):
            raise RuntimeError('a new private desktop and every save lock are required')
        executable = Path(executable).resolve(strict=True)
        command = subprocess.list2cmdline([str(executable), *arguments])
        buffer = ctypes.create_unicode_buffer(command)
        station = self.object_name(self.user.GetProcessWindowStation())
        desktop = f'{station}\\{self.name}'
        env_buffer = None
        if env is not None:
            entries = (f'{key}={value}' for key, value in sorted(env.items(), key=lambda pair: pair[0].upper()))
            env_buffer = ctypes.create_unicode_buffer('\x00'.join(entries) + '\x00\x00')
        inherited = []
        current = locks._kernel.GetCurrentProcess()
        attributes = None
        try:
            for source in locks._handles:
                copied = w.HANDLE()
                if not locks._kernel.DuplicateHandle(current, source, current, ctypes.byref(copied), 0, True, 2):
                    raise ctypes.WinError(ctypes.get_last_error())
                inherited.append(copied.value)
            allowed = (w.HANDLE * len(inherited))(*inherited)
            size = ctypes.c_size_t()
            self.kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            storage = ctypes.create_string_buffer(size.value)
            if not self.kernel.InitializeProcThreadAttributeList(storage, 1, 0, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = storage
            handle_list = 0x20002  # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
            if not self.kernel.UpdateProcThreadAttribute(
                attributes, 0, handle_list, allowed, ctypes.sizeof(allowed), None, None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            start = _StartupInfoEx()
            start.startup.cb = ctypes.sizeof(start)
            start.startup.desktop = desktop
            start.startup.flags = 0x81  # hide the initial window and prevent cursor feedback
            start.attributes = ctypes.cast(attributes, w.LPVOID)
            result = _ProcessInfo()
            extended_startupinfo, unicode_environment = 0x80000, 0x400
            flags = (extended_startupinfo | unicode_environment
                     | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
            if not self.kernel.CreateProcessW(str(executable), buffer, None, None, True, flags, env_buffer,
                                               str(cwd) if cwd else None, ctypes.byref(start), ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.kernel.CloseHandle(result.thread)
            self.child = _Child(self.kernel, result, command)
            return self.child
        finally:
            if attributes is not None:
                self.kernel.DeleteProcThreadAttributeList(attributes)
            for handle in inherited:
                locks._kernel.CloseHandle(handle)

    def __exit__(self, *_):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.terminate()
                self.child.wait(timeout=10)
            self.kernel.CloseHandle(self.child.handle)
            self.child = None
        if self.handle:
            self.user.CloseDesktop(self.handle)
            self.handle = None
