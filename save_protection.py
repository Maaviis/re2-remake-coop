"""Validate fresh local receipts from the inherited-lock launcher and native barrier."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


def read_save_protection(data, *, now=None):
    now = time.time() if now is None else now
    data = Path(data)
    native = json.loads((data / 're2_coop_native_save_guard.json').read_text(encoding='utf-8'))
    launch = json.loads((data / 're2_coop_protected_launch.json').read_text(encoding='utf-8'))
    for value, source in ((native, 'steam_storage_guard'), (launch, 'inherited_save_locks')):
        if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
                or value.get('source') != source or value.get('active') is not True
                or type(value.get('at')) is not int or not 0 <= now - value['at'] <= 3
                or type(value.get('game_pid')) is not int or value['game_pid'] <= 0
                or not isinstance(value.get('run_id'), str)
                or not re.fullmatch('[0-9a-f]{32}', value['run_id'])
                or type(value.get('app_id')) is not int or value['app_id'] != 883710
                or type(value.get('build_id')) is not int or value['build_id'] != 11636119):
            raise ValueError('protected_launch_required: invalid or expired protection receipt')
    if (native.get('reason') != 'ok' or native.get('interface') != '014'
            or type(native.get('guarded_methods')) is not int or native['guarded_methods'] != 10
            or type(launch.get('locked_files')) is not int or launch['locked_files'] <= 0
            or native['game_pid'] != launch['game_pid'] or native['run_id'] != launch['run_id']):
        raise ValueError('protected_launch_required: protection binding mismatch')
    return {'game_pid': native['game_pid'], 'run_id': native['run_id']}


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


def storage_guard_active(directory):
    if sys.platform != "win32":
        return False
    import _winapi
    import msvcrt

    # Match the Windows wrapper's invariant casing, including paths containing sharp-s.
    path_key = _winapi.LCMapStringEx(_winapi.LOCALE_NAME_INVARIANT, _winapi.LCMAP_UPPERCASE, str(directory))
    path_hash = sha256(path_key.encode("utf-8")).hexdigest().upper()
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    marker = Path(local) / "RE2Coop" / "save-guard" / f"{path_hash}.active"
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
