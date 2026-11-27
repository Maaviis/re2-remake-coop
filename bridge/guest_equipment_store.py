"""Host-side guest equipment for one protected RE2 campaign."""

from contextlib import contextmanager
from hashlib import sha256
import os
import secrets
from threading import Lock

from campaign_save_copy import _directory_id, _entry
from coop_checkpoint import HostArchive, _token
from guest_equipment_format import MAX_BYTES, valid_equipment
from load_witness import _read_json
from lobby_sync import write_json
from sync_model import state_digest


_thread_lock = Lock()


def _equipment_copy(value):
    if not isinstance(value, dict) or value.keys() != {'equipment'}:
        raise ValueError('Missing or invalid guest equipment.')
    wire = value.get('equipment')
    if not valid_equipment(wire):
        raise ValueError('Missing or invalid guest equipment.')
    return {'equipment': wire}


def _account_key(account_id):
    if type(account_id) is int and 0 < account_id < 2**64:
        account_id = str(account_id)
    if (not isinstance(account_id, str) or not 1 <= len(account_id) <= 20
            or not account_id.isascii() or not account_id.isdecimal()
            or account_id[0] == '0' or int(account_id) >= 2**64):
        raise ValueError('Invalid guest account.')
    return sha256(account_id.encode('ascii')).hexdigest()


class GuestEquipmentStore:
    def __init__(self, solo_save_path, campaign_namespace):
        archive = HostArchive(solo_save_path, campaign_namespace)
        self.root = archive.root / 'guest-equipment'
        self.namespace = archive.namespace

    @contextmanager
    def _locked(self):
        # Both bridge restarts and concurrent workers must serialize the read/check/replace.
        with _thread_lock:
            for directory in (self.root.parent.parent, self.root.parent, self.root):
                directory.mkdir(exist_ok=True)
                _directory_id(directory)
            lock_path = self.root / 'equipment.lock'
            _entry(lock_path, directory=False, missing_ok=True)
            with lock_path.open('a+b') as stream:
                if os.name == 'nt':
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX)
                yield

    def _digest(self, account_key, lease, equipment):
        return state_digest([self.namespace, account_key, lease, equipment])

    def _read(self, account_key):
        path = self.root / (account_key + '.json')
        if _entry(path, directory=False, missing_ok=True) is None:
            return None
        try:
            record = _read_json(path, max_bytes=MAX_BYTES + 512)
        except RecursionError as exc:
            raise ValueError('Invalid guest equipment file.') from exc
        if (not isinstance(record, dict) or set(record) != {'schema', 'lease', 'equipment', 'digest'}
                or type(record['schema']) is not int or record['schema'] != 1 or not _token(record['lease'])):
            raise ValueError('Invalid guest equipment file.')
        equipment = _equipment_copy(record['equipment'])
        if record['digest'] != self._digest(account_key, record['lease'], equipment):
            raise ValueError('Guest equipment file failed its integrity check.')
        return record

    def _write(self, account_key, lease, equipment):
        write_json(self.root / (account_key + '.json'), {
            'schema': 1, 'lease': lease, 'equipment': equipment,
            'digest': self._digest(account_key, lease, equipment),
        })

    def join(self, guest_account_id, host_equipment):
        """Issue a fresh lease and restore this guest, seeding only on their first join."""
        account_key = _account_key(guest_account_id)
        with self._locked():
            record = self._read(account_key)
            equipment = _equipment_copy(host_equipment) if record is None else record['equipment']
            lease = secrets.token_hex(16)
            self._write(account_key, lease, equipment)
            return lease, equipment

    def save(self, guest_account_id, lease, equipment):
        """Publish only while this attachment still owns the guest's inventory."""
        account_key = _account_key(guest_account_id)
        with self._locked():
            record = self._read(account_key)
            if record is None or not _token(lease) or record['lease'] != lease:
                raise ValueError('Guest equipment attachment expired.')
            self._write(account_key, lease, _equipment_copy(equipment))
