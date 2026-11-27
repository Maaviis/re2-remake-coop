"""Recoverable replacement of the active Steam RE2 save directory with a local copy."""

from contextlib import contextmanager
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import NamedTuple
from uuid import uuid4

from load_preflight import MAX_SAVE_BYTES
from pose_bridge import lock_data_directory
from save_protection import storage_guard_recovery_pending


STATE_DIR = 're2-coop-save-sessions'


class _Transaction(NamedTuple):
    work: Path
    original_id: tuple
    copy_id: tuple


def _entry(path, *, directory, missing_ok=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected_type(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not info.st_ino or (not directory and info.st_nlink != 1)):
        raise ValueError('Unexpected filesystem entry in the campaign save directory')
    return info


def _identity(info):
    return (info.st_dev, info.st_ino) if info is not None else None


def _directory_id(path, *, missing_ok=False):
    return _identity(_entry(path, directory=True, missing_ok=missing_ok))


def _file_signature(info):
    return _identity(info), info.st_size, info.st_mtime_ns


def _inventory(directory):
    result = {}
    for path in directory.iterdir():
        info = _entry(path, directory=False)
        if len(result) == 128 or info.st_size > MAX_SAVE_BYTES:
            raise ValueError('Unsupported RE2 save inventory')
        result[path.name] = _file_signature(info)
    if not result:
        raise ValueError('The RE2 save directory is empty')
    return result


def _copy_files(source, target, inventory):
    for name, before in inventory.items():
        with (source / name).open('rb') as original:
            if _file_signature(os.fstat(original.fileno())) != before:
                raise ValueError('RE2 save changed before copying')
            contents = original.read(before[1] + 1)
            if len(contents) != before[1] or _file_signature(os.fstat(original.fileno())) != before:
                raise ValueError('RE2 save changed while copying')
        with (target / name).open('xb') as copy:
            copy.write(contents)
            copy.flush()
            os.fsync(copy.fileno())
        with (target / name).open('rb') as copy:
            if file_digest(copy, 'sha256').digest() != sha256(contents).digest():
                raise ValueError('RE2 test copy failed digest verification')


def _move_directory(source, target, expected):
    if _directory_id(source) != expected or _directory_id(target, missing_ok=True) is not None:
        raise ValueError('RE2 save directory changed before switching')
    os.rename(source, target)


@contextmanager
def open_save_session(directory, require_closed, *, steam_userdata=None):
    """Hold the exclusive session lock through staging, protection and recovery."""
    directory = Path(directory)
    remote, app, account, userdata = directory.parents[:4] if len(directory.parents) >= 4 else (None,) * 4
    if (not directory.is_absolute() or userdata is None
            or (userdata.name != 'userdata' if steam_userdata is None else userdata != steam_userdata)
            or (app.name, remote.name, directory.name) != ('883710', 'remote', 'win64_save')
            or not re.fullmatch(r'[0-9]+', account.name)):
        raise ValueError('Expected the active Steam RE2 save path')
    volume = _directory_id(app)[0]
    for parent in (userdata, account, remote):
        if _directory_id(parent)[0] != volume:
            raise ValueError('RE2 save session requires a single volume')
    if remote.resolve(strict=True) != remote:
        raise ValueError('RE2 save path must be canonical')
    state = app / STATE_DIR
    state.mkdir(exist_ok=True)
    if _directory_id(state)[0] != volume:
        raise ValueError('The RE2 copy must be on the same volume')
    _entry(state / 're2_coop_save_copy_bridge.lock', directory=False, missing_ok=True)
    with lock_data_directory(state, stream='save_copy'):
        yield _SaveSession(directory, state, require_closed)


def _read_transaction(state):
    journal = state / 'active.json'
    if _entry(journal, directory=False, missing_ok=True) is None:
        return None
    volume = _directory_id(state)[0]
    with journal.open('rb') as stream:
        data = stream.read(4096)
    if len(data) == 4096:
        raise ValueError('Invalid RE2 save recovery record')
    record = json.loads(data)
    if (not isinstance(record, dict) or set(record) != {'schema', 'session', 'original', 'copy'}
            or type(record['schema']) is not int or record['schema'] != 1
            or not isinstance(record['session'], str) or not re.fullmatch('[0-9a-f]{32}', record['session'])):
        raise ValueError('Invalid RE2 save recovery record')
    for key in ('original', 'copy'):
        identity = record[key]
        if (not isinstance(identity, list) or len(identity) != 2
                or any(type(value) is not int for value in identity)
                or identity[0] != volume or identity[1] <= 0):
            raise ValueError('Invalid RE2 save recovery identity')
    original_id, copy_id = tuple(record['original']), tuple(record['copy'])
    work = state / record['session']
    if _directory_id(work)[0] != volume or original_id == copy_id:
        raise ValueError('Invalid RE2 save recovery directory')
    return _Transaction(work, original_id, copy_id)


def check_managed_save(directory, *, required=False):
    """If this directory has a managed session, verify the active copy and backup."""
    transaction = _read_transaction(directory.parent.parent / STATE_DIR)
    if transaction is None:
        if required:
            raise ValueError('Eine verwaltete Spielstandkopie ist erforderlich.')
        return
    work, original_id, copy_id = transaction
    if (_directory_id(directory) != copy_id or _directory_id(work / 'original') != original_id
            or _directory_id(work / 'copy', missing_ok=True) is not None):
        raise ValueError('Die geschuetzte Spielstandkopie oder ihr Originalordner fehlt.')


class _SaveSession:
    def __init__(self, directory, state, require_closed):
        self.directory = directory
        self.state = state
        self.journal = state / 'active.json'
        self.require_closed = require_closed

    def _require_switchable(self):
        self.require_closed()
        if storage_guard_recovery_pending(self.directory):
            raise ValueError('Restore the Windows save access rules before switching RE2 save directories')

    def install(self):
        self._require_switchable()
        if _entry(self.journal, directory=False, missing_ok=True) is not None:
            raise ValueError('Restore the previous RE2 save session first')
        active = self.directory
        original_id = _directory_id(active)
        if original_id[0] != _directory_id(self.state)[0]:
            raise ValueError('The RE2 copy must be on the same volume')
        inventory = _inventory(active)
        token = uuid4().hex
        work = self.state / token
        copy = work / 'copy'
        copy.mkdir(parents=True)
        copy_id = _directory_id(copy)
        _copy_files(active, copy, inventory)
        record = work / 'pending.json'
        with record.open('x', encoding='utf-8') as stream:
            json.dump({'schema': 1, 'session': token, 'original': original_id, 'copy': copy_id}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        self._require_switchable()
        if _directory_id(active) != original_id or _inventory(active) != inventory:
            raise ValueError('RE2 save inventory changed during copying')
        os.rename(record, self.journal)
        _move_directory(active, work / 'original', original_id)
        _move_directory(copy, active, copy_id)
        return work / 'guard-ready'

    def restore(self):
        transaction = _read_transaction(self.state)
        if transaction is None:
            return None
        self._require_switchable()
        work, original_id, copy_id = transaction
        active, original, copy = self.directory, work / 'original', work / 'copy'
        current = _directory_id(active, missing_ok=True)
        backup = _directory_id(original, missing_ok=True)
        saved_copy = _directory_id(copy, missing_ok=True)
        if (current, backup, saved_copy) == (copy_id, original_id, None):
            _move_directory(active, copy, copy_id)
            current, saved_copy = None, copy_id
        if (current, backup, saved_copy) == (None, original_id, copy_id):
            _move_directory(original, active, original_id)
            current, backup = original_id, None
        if (current, backup, saved_copy) != (original_id, None, copy_id):
            raise ValueError('RE2 save recovery found an unexpected directory. Original and test files are retained.')
        os.rename(self.journal, work / 'restored.json')
        return copy
