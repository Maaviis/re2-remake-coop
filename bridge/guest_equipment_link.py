"""Exchange personal equipment on the existing authenticated Steam pose connection."""
import re
from struct import Struct
import time

from guest_equipment_format import MAX_BYTES, valid_equipment
from guest_equipment_store import GuestEquipmentStore
from load_witness import _read_json
from lobby_sync import write_json

# serial 0 is a host offer. Positive serials are complete guest inventories.
# A zero-part response acknowledges that the host has committed that serial.
MAGIC = b'R2I1'
# Local Steam epochs differ across machines. The pose handshake and campaign attempt are shared.
HEADER = Struct('!4s16s16s16sIBB')
CHUNK = 4096 - HEADER.size
MAX_PARTS = (MAX_BYTES + CHUNK - 1) // CHUNK
TOKEN = re.compile(r'[0-9a-f]{32}')


def fresh_json(path, now):
    value = _read_json(path, max_bytes=MAX_BYTES + 4096)
    if (not isinstance(value, dict) or value.get('schema') != 1 or type(value.get('at')) is not int
            or not 0 <= now - value['at'] <= 2):
        raise ValueError('Gastinventar wartet auf aktuelle Spieldaten.')
    return value


class GuestEquipmentLink:
    def __init__(self, data, pid, role):
        self.data, self.pid, self.role = data, pid, role.decode()
        self.clear()

    def clear(self):
        self.key = self.sample = self.lease = self.store = self.account = self.initial = None
        self.outgoing = self.parts = self.part_key = None
        self.serial = self.ack = self.part = 0
        self.next_sample = self.next_send = self.next_command = 0
        self.last_error = None

    def _sample(self, transport, handshake, binding, directory, wall):
        sample = fresh_json(self.data / 're2_coop_equipment_local.json', wall)
        if (sample.get('pid') != self.pid or sample.get('role') != self.role
                or sample.get('session') != handshake[0] or sample.get('namespace') != binding['campaign_namespace']
                or type(sample.get('revision')) is not int or not 1 <= sample['revision'] <= 0xffffffff
                or not isinstance(sample.get('snapshot_epoch'), str)
                or not re.fullmatch(r'[0-9a-f]{16}', sample['snapshot_epoch'])
                or not valid_equipment(sample.get('equipment'))
                or not all(isinstance(sample.get(k), str) and TOKEN.fullmatch(sample[k])
                           for k in ('attempt', 'request'))):
            return None
        peer = fresh_json(self.data / 're2_coop_native_peer.json', wall)
        if (peer.get('game_pid') != self.pid or peer.get('role') != self.role
                or type(peer.get('revision')) is not int or peer.get('revision') != sample.get('revision')
                or peer.get('snapshot_epoch') != sample.get('snapshot_epoch')):
            return None
        account = None
        if self.role == 'H':
            account = peer.get('guest_account_id')
            if (not isinstance(account, str) or not account.isascii() or not account.isdecimal()
                    or peer.get('equipment_pose_epoch') != transport.epoch.hex()):
                return None
        key = (handshake, transport.epoch, sample['attempt'], sample['request'], sample['namespace'], account)
        if self.key != key:
            self.clear()
            if self.role == 'H':
                store = GuestEquipmentStore(directory, sample['namespace'])
                lease, saved = store.join(account, {'equipment': sample['equipment']})
                if not valid_equipment(saved.get('equipment')):
                    raise ValueError('Das gespeicherte Gastinventar ist ungültig.')
                self.store, self.account, self.lease, self.outgoing = store, account, lease, saved['equipment']
            self.key = key
        return sample

    def _send(self, transport, serial, index, count, payload=b''):
        transport.send_payload(HEADER.pack(MAGIC, bytes.fromhex(self.key[0][1]), bytes.fromhex(self.key[2]),
                                          bytes.fromhex(self.lease), serial, index, count) + payload)

    def _receive(self, transport, packet):
        if not HEADER.size <= len(packet) <= 4096:
            return
        magic, request, attempt, token, serial, index, count = HEADER.unpack_from(packet)
        if magic != MAGIC or request.hex() != self.key[0][1] or attempt.hex() != self.key[2]:
            return
        lease = token.hex()
        if self.lease and self.lease != lease:
            return
        body = packet[HEADER.size:]
        if not count:
            if self.role == 'G' and self.lease == lease and serial == self.serial and not index and not body:
                self.ack = serial
            return
        if (self.role == 'G' and serial != 0) or (self.role == 'H' and serial == 0):
            return
        if self.role == 'H' and serial <= self.ack:
            if serial == self.ack:
                self._send(transport, serial, 0, 0)
            return
        if not (0 <= index < count <= MAX_PARTS and 0 < len(body) <= CHUNK
                and (index == count - 1 or len(body) == CHUNK) and index * CHUNK + len(body) <= MAX_BYTES):
            return
        key = lease, serial, count
        if self.part_key != key:
            if self.part_key and serial < self.part_key[1]:
                return
            self.part_key, self.parts = key, {}
        self.parts[index] = body
        if len(self.parts) != count:
            return
        value = b''.join(self.parts[i] for i in range(count)).decode('ascii')
        self.parts, self.part_key = {}, None
        if not valid_equipment(value):
            return
        if self.role == 'H':
            self.store.save(self.account, self.lease, {'equipment': value})
            self.ack = serial
            self._send(transport, serial, 0, 0)
        elif self.lease is None:
            self.lease, self.initial = lease, value

    def tick(self, transport, handshake, source, packet=None):
        binding = getattr(source, 'campaign_binding', None)
        if (not handshake[0] or not handshake[1] or not binding or not transport.epoch
                or self.key and (self.key[0] != handshake or self.key[1] != transport.epoch)):
            if self.key:
                self.clear()
            return
        now, wall = time.monotonic(), int(time.time())
        try:
            if now >= self.next_sample:
                self.sample = None
                self.sample = self._sample(transport, handshake, binding, source.supplied_directory, wall)
                self.next_sample = now + .25
            if self.sample is None or not 0 <= wall - self.sample['at'] <= 2:
                return
            if packet is not None:
                self._receive(transport, packet)
            if self.role == 'G' and self.lease:
                if self.sample.get('lease') != self.lease:
                    if now >= self.next_command:
                        command = {key: self.sample[key] for key in
                                   ('pid', 'role', 'session', 'attempt', 'request', 'revision', 'snapshot_epoch', 'namespace')}
                        # Lua can reload while the bridge still owns this attachment. Preserve the last
                        # verified local inventory, including an update whose host ACK is still in flight.
                        restore = self.outgoing if self.outgoing is not None else self.initial
                        write_json(self.data / 're2_coop_equipment_restore.json',
                                   {**command, 'schema': 1, 'at': wall, 'lease': self.lease, 'equipment': restore,
                                    'reader_run': self.sample.get('reader_run')})
                        self.next_command = now + .5
                    return
                if self.outgoing != self.sample['equipment']:
                    self.outgoing = self.sample['equipment']
                    self.serial += 1
                    self.part = self.next_send = 0
            if (not self.outgoing or now < self.next_send or self.role == 'H' and self.ack
                    or self.role == 'G' and self.serial == self.ack):
                return
            count = (len(self.outgoing) + CHUNK - 1) // CHUNK
            start = self.part * CHUNK
            self._send(transport, self.serial, self.part, count, self.outgoing[start:start+CHUNK].encode('ascii'))
            self.part = (self.part + 1) % count
            self.next_send = now + (.02 if self.part else 1.0)
        except (ValueError, KeyError, TypeError, RecursionError, OSError) as exc:
            # Invalid/absent samples and transient file conflicts cannot interrupt movement or seed a new profile.
            # Retry at the normal sample cadence. Report a storage failure only on transition.
            self.next_sample = now + .25
            if not isinstance(exc, FileNotFoundError) and self.last_error != type(exc):
                print('Gastinventar: Übertragung oder Speicherung wird erneut versucht (' + type(exc).__name__ + ').',
                      flush=True)
                self.last_error = type(exc)
