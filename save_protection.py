"""Validate fresh local receipts from the native barrier and the active file locks."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


def _valid_receipt(value, source, now):
    return (isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] == 1
            and value.get('source') == source and value.get('active') is True
            and type(value.get('at')) is int and 0 <= now - value['at'] <= 3
            and type(value.get('game_pid')) is int and value['game_pid'] > 0
            and isinstance(value.get('run_id'), str)
            and re.fullmatch('[0-9a-f]{32}', value['run_id']) is not None
            and type(value.get('app_id')) is int and value['app_id'] == 883710
            and type(value.get('build_id')) is int and value['build_id'] == 11636119)


def read_save_protection(data, *, now=None, allow_runtime=True, runtime_directory=None):
    now = time.time() if now is None else now
    data = Path(data)
    native = json.loads((data / 're2_coop_native_save_guard.json').read_text(encoding='utf-8'))
    if not _valid_receipt(native, 'steam_storage_guard', now):
        raise ValueError('protected_launch_required: invalid or expired protection receipt')
    if (native.get('reason') != 'ok' or native.get('interface') != '014'
            or type(native.get('guarded_methods')) is not int or native['guarded_methods'] != 10):
        raise ValueError('protected_launch_required: native barrier missing')
    binding = {'game_pid': native['game_pid'], 'run_id': native['run_id']}
    if 'runtime_locked_files' in native:
        if not allow_runtime:
            raise ValueError('runtime protection requires a prepared Steam campaign')
        count = native['runtime_locked_files']
        if type(count) is not int or not 1 <= count <= 128:
            raise ValueError('protected_launch_required: runtime file protection missing')
        reported = native.get('runtime_save_path')
        if not isinstance(reported, str) or not Path(reported).is_absolute():
            raise ValueError('protected_launch_required: runtime save directory missing')
        if runtime_directory is not None and not Path(reported).samefile(runtime_directory):
            raise ValueError('protected_launch_required: runtime save directory changed')
        return binding
    launch = json.loads((data / 're2_coop_protected_launch.json').read_text(encoding='utf-8'))
    if (not _valid_receipt(launch, 'inherited_save_locks', now)
            or type(launch.get('locked_files')) is not int or launch['locked_files'] <= 0
            or any(launch[key] != value for key, value in binding.items())):
        raise ValueError('protected_launch_required: protection binding mismatch')
    return binding


def active_save_identity(pipe, directory):
    active_directory = pipe.save_directory()
    if active_directory is None:
        raise ValueError("cannot determine the active Steam save directory for RE2")
    try:
        active = active_directory.stat()
        selected = directory.stat()
    except OSError as exc:
        raise ValueError("cannot read the active Steam save directory for RE2") from exc
    if any(not entry.st_ino or not stat.S_ISDIR(entry.st_mode) for entry in (active, selected)):
        raise ValueError("cannot identify the active Steam save directory for RE2")
    identity = active.st_dev, active.st_ino
    if identity != (selected.st_dev, selected.st_ino):
        raise ValueError("select the active Steam save directory containing the isolated test copy")
    return identity


def _storage_guard_record(directory, suffix):
    if sys.platform != "win32":
        return None
    import _winapi

    # Match the Windows wrapper's invariant casing, including paths containing sharp-s.
    path_key = _winapi.LCMapStringEx(_winapi.LOCALE_NAME_INVARIANT, _winapi.LCMAP_UPPERCASE, str(directory))
    path_hash = sha256(path_key.encode("utf-8")).hexdigest().upper()
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "RE2Coop" / "save-guard" / (path_hash + suffix) if local else None


def storage_guard_recovery_pending(directory):
    record = _storage_guard_record(directory, '.json')
    if record is None:
        return False
    try:
        record.lstat()
    except FileNotFoundError:
        return False
    return True


def storage_guard_active(directory):
    marker = _storage_guard_record(directory, '.active')
    if marker is None:
        return False
    import _winapi
    import msvcrt

    path_key = _winapi.LCMapStringEx(_winapi.LOCALE_NAME_INVARIANT, _winapi.LCMAP_UPPERCASE, str(directory))
    handle = None
    try:
        # Share deletion with the wrapper's delete-on-close handle while reading its proof.
        handle = _winapi.CreateFile(str(marker), _winapi.GENERIC_READ, 7, 0, _winapi.OPEN_EXISTING, 0, 0)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        handle = None
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            proof = json.loads(stream.read(32769))
        if (not isinstance(proof, dict) or type(proof.get("schema")) is not int or proof["schema"] != 1
                or not isinstance(proof.get("directory"), str)
                or _winapi.LCMapStringEx(_winapi.LOCALE_NAME_INVARIANT, _winapi.LCMAP_UPPERCASE,
                                        proof["directory"]) != path_key):
            return False
        try:
            handle = _winapi.CreateFile(str(marker), _winapi.GENERIC_WRITE, 7, 0,
                                        _winapi.OPEN_EXISTING, 0, 0)
        except OSError as exc:
            return exc.winerror == 32
        return False
    except (OSError, ValueError):
        return False
    finally:
        if handle is not None:
            _winapi.CloseHandle(handle)
