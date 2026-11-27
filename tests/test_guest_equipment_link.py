from collections import deque
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guest_equipment_link import CHUNK, HEADER, MAGIC, GuestEquipmentLink
from load_preflight import NativeSaveSource
from lobby_sync import write_json


NAMESPACE = 'a' * 32
ACCOUNT = '76561198012345678'
SECOND_ACCOUNT = '76561198012345679'
EMPTY = 'E1,8,0,-1,-1,-1,0,0,0'
HOST = 'E1,8,1,0,1,0,1,0,15,9,0,0,0,1,-1,0,1,0,1,0,0'
AMMO = 'E1,8,1,0,0,15,-1,0,0,12,0,0,-1,-1,-1,0,0,0'
LOCAL = 're2_coop_equipment_local.json'
NATIVE = 're2_coop_native_peer.json'
RESTORE = 're2_coop_equipment_restore.json'


def read(path):
    return json.loads(path.read_bytes())


class Endpoint:
    def __init__(self, root, role, pid):
        self.role, self.pid = role, pid
        self.data = root / role / 'data'
        self.data.mkdir(parents=True)
        self.solo = root / role / str(pid) / '883710/remote/win64_save'
        self.solo.mkdir(parents=True)
        self.original = self.solo / 'data000.bin'
        self.original.write_bytes(b'original native save')
        self.source = NativeSaveSource(self.data, self.solo, allow_date=None,
                                       campaign_binding={'campaign_namespace': NAMESPACE})
        self.link = GuestEquipmentLink(self.data, pid, role.encode())
        self.received = deque()
        self.equipment = HOST if role == 'H' else EMPTY
        self.sample_changes, self.native_changes = {}, {}
        self.lease = None
        self.reader_run = 'first-runtime'
        self.receipt_changes = {}
        self.archive = NAMESPACE

    def send_payload(self, data):
        self.other.received.append(data)

    def publish(self, wall, handshake, generation):
        snapshot = (b'snapshot' if self.role == 'H' else b'snap_gst').hex()
        self.scope = dict(pid=self.pid, role=self.role, revision=generation, snapshot_epoch=snapshot,
                          session=handshake[0], attempt=f'{generation+10:032x}',
                          release_id=f'{generation+20:032x}',
                          request=f'{generation+self.pid:032x}', namespace=self.source.campaign_binding['campaign_namespace'],
                          reader_run=self.reader_run)
        sample = dict(self.scope, schema=1, at=wall, equipment=self.equipment, lease=self.lease)
        native = dict(schema=1, at=wall, game_pid=self.pid, revision=generation, snapshot_epoch=snapshot, role=self.role)
        if self.role == 'H':
            native.update(guest_account_id=ACCOUNT, equipment_pose_epoch=self.epoch.hex())
            write_json(self.data / 're2_coop_campaign_checkpoint.json', {
                'schema': 1, 'game_pid': self.pid, 'load_request_id': self.scope['request'],
                'attempt_id': self.scope['attempt'], 'snapshot_epoch': snapshot, 'release_id': self.scope['release_id'],
                'protection': self.source.campaign_binding, 'archive_namespace': self.archive,
                'checkpoint_match': True, 'native_pause_match': True, 'resume_authorized': True,
                **self.receipt_changes})
        write_json(self.data / LOCAL, {**sample, **self.sample_changes})
        write_json(self.data / NATIVE, {**native, **self.native_changes})


class EquipmentLinkTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.host, self.guest = Endpoint(root, 'H', 101), Endpoint(root, 'G', 202)
        self.host.other, self.guest.other = self.guest, self.host
        self.elapsed = 100.0
        self.clock = SimpleNamespace(monotonic=lambda: self.elapsed, time=lambda: 1700000000 + self.elapsed)
        self.enterContext(patch('guest_equipment_link.time', self.clock))
        self.connect(1)

    def connect(self, generation):
        self.generation = generation
        self.handshake = (f'{generation:032x}', f'{generation+100:032x}')
        for endpoint in (self.host, self.guest):
            endpoint.epoch = (endpoint.pid + generation).to_bytes(8, 'big')
            endpoint.lease = None
            endpoint.received.clear()

    def disconnect(self):
        for endpoint in (self.host, self.guest):
            endpoint.epoch = None
            endpoint.link.tick(endpoint, (None, None), endpoint.source)

    def step(self, count=1):
        for _ in range(count):
            self.elapsed += .3
            for endpoint in (self.host, self.guest):
                endpoint.publish(int(self.clock.time()), self.handshake, self.generation)
                packet = endpoint.received.popleft() if endpoint.received else None
                endpoint.link.tick(endpoint, self.handshake, endpoint.source, packet)

    def readback(self, expected):
        # Simulate the Lua publisher after the native write and full inventory readback.
        self.step(2)
        command = read(self.guest.data / RESTORE)
        self.assertEqual({key: command[key] for key in self.guest.scope}, self.guest.scope)
        self.assertEqual(command['equipment'], expected)
        self.assertRegex(command['lease'], r'^[0-9a-f]{32}$')
        self.guest.equipment, self.guest.lease = expected, command['lease']
        self.step(3)
        return command['lease']

    def record(self, account=ACCOUNT):
        digest = sha256(account.encode()).hexdigest()
        return self.host.solo.parent.parent / 're2-coop-checkpoints' / NAMESPACE / 'guest-equipment' / (digest + '.json')

    def assert_private(self, equipment, account=ACCOUNT):
        self.assertEqual(read(self.record(account))['equipment'], {'equipment': equipment})
        self.assertEqual(read(self.host.data / LOCAL)['equipment'], self.host.equipment)
        self.assertFalse((self.host.data / RESTORE).exists())
        for endpoint in (self.host, self.guest):
            self.assertEqual(list(endpoint.solo.iterdir()), [endpoint.original])
            self.assertEqual(endpoint.original.read_bytes(), b'original native save')

    def packet(self, lease, body, serial=100, index=0, count=1):
        return HEADER.pack(MAGIC, bytes.fromhex(self.handshake[1]), bytes.fromhex(self.host.scope['attempt']),
                           bytes.fromhex(lease), serial, index, count) + body

    def dropped_shot(self, deliver, *, changed_account=False, skip_host_offers=False, restore_checkpoint=False):
        ten = HOST.replace(',15,9,', ',15,10,')
        self.host.equipment = ten
        lease = self.readback(ten)
        command = read(self.guest.data / RESTORE)
        # Reproduce the durable native publisher in test_guest_equipment_runtime_lua.
        # No guest-side transport poll is required to observe the shot.
        write_json(self.guest.data / f"re2_coop_equipment_pending_{command['profile']}.json",
                       dict(schema=1, profile=command['profile'], lease=lease, writer=command['writer'], equipment=HOST))
        self.guest.equipment = HOST
        if deliver:
            self.step()
            self.host.link.tick(self.host, self.handshake, self.host.source, self.host.received.popleft())
            self.assertLess(self.guest.link.ack, self.guest.link.serial)
        self.assert_private(HOST if deliver else ten)
        self.disconnect()
        self.connect(2)
        if restore_checkpoint:
            for endpoint in (self.host, self.guest):
                endpoint.source = NativeSaveSource(endpoint.data, endpoint.solo, allow_date=None,
                    campaign_binding={'campaign_namespace': f'{endpoint.pid:032x}'})
        if skip_host_offers:
            self.step()
            self.disconnect()
            self.connect(3)
        if changed_account:
            self.host.native_changes['guest_account_id'] = SECOND_ACCOUNT
        self.guest.link = GuestEquipmentLink(self.guest.data, self.guest.pid, b'G')
        self.guest.reader_run = 'new-attachment'
        # A cold checkpoint load starts both survivors from the host save.
        self.guest.equipment = ten if restore_checkpoint else EMPTY
        expected = ten if changed_account else HOST
        self.assertNotEqual(self.readback(expected), lease)
        self.assert_private(expected, SECOND_ACCOUNT if changed_account else ACCOUNT)
        self.assertEqual(self.host.equipment, ten)

    def test_shot_before_guest_bridge_poll_survives_disconnect(self):
        self.dropped_shot(False)

    def test_checkpoint_in_fresh_workspaces_keeps_the_unconfirmed_guest_shot(self):
        self.dropped_shot(False, restore_checkpoint=True)
        root = self.host.solo.parent.parent / 're2-coop-checkpoints'
        self.assertEqual({p.name for p in root.iterdir()}, {NAMESPACE})

    def test_new_campaign_rejects_the_previous_receipt_and_guest_journal(self):
        self.dropped_shot(False, restore_checkpoint=True)
        previous = read(self.host.data / 're2_coop_campaign_checkpoint.json')
        old_profile = read(self.guest.data / RESTORE)['profile']
        self.disconnect()
        self.connect(3)
        self.host.archive = 'b' * 32
        self.host.source = NativeSaveSource(self.host.data, self.host.solo, allow_date=None,
            campaign_binding={'campaign_namespace': self.host.archive})
        self.host.receipt_changes = previous
        self.step(3)
        self.assertFalse((self.record().parent.parent.parent / self.host.archive).exists())
        self.assertIsNone(self.guest.link.lease)
        self.host.receipt_changes = {}
        self.readback(self.host.equipment)
        self.assertNotEqual(read(self.guest.data / RESTORE)['profile'], old_profile)
        self.assertEqual(read(self.record())['equipment']['equipment'], HOST)

    def test_stale_or_unconfirmed_campaign_receipt_cannot_open_an_equipment_profile(self):
        for change in ({'attempt_id': 'f'*32}, {'load_request_id': 'f'*32}, {'game_pid': 202},
                       {'snapshot_epoch': 'f'*16}, {'release_id': 'f'*32}, {'protection': {'campaign_namespace': 'e'*32}},
                       {'archive_namespace': 'bad'}, {'resume_authorized': False},
                       {'checkpoint_match': False}, {'native_pause_match': False}):
            with self.subTest(change=change):
                self.host.receipt_changes = change
                self.step(2)
                self.assertFalse(self.record().exists())
                self.assertFalse((self.guest.data / RESTORE).exists())

    def test_shot_saved_on_host_but_ack_lost(self):
        self.dropped_shot(True)

    def test_unreceived_shot_survives_interrupted_second_join(self):
        self.dropped_shot(False, skip_host_offers=True)

    def test_other_account_cannot_inherit_unreceived_shot(self):
        self.dropped_shot(False, changed_account=True)

    def test_stale_writer_cannot_override_another_device_in_the_same_profile(self):
        self.dropped_shot(False)
        recent = read(self.guest.data / RESTORE)
        self.guest.equipment = AMMO
        self.step(5)
        self.assert_private(AMMO)
        # The first device is back with its old local cache. Another lease has committed.
        self.disconnect()
        self.connect(4)
        self.guest.link = GuestEquipmentLink(self.guest.data, self.guest.pid, b'G')
        self.assertNotEqual(self.readback(AMMO), recent['lease'])
        self.assert_private(AMMO)

    def test_damaged_local_journal_keeps_the_confirmed_host_inventory(self):
        self.readback(HOST)
        profile = read(self.guest.data / RESTORE)['profile']
        (self.guest.data / f're2_coop_equipment_pending_{profile}.json').write_bytes(b'{')
        self.disconnect()
        self.connect(2)
        self.readback(HOST)
        self.assert_private(HOST)

    def test_confirmed_round_spent_survives_a_new_guest_attachment(self):
        # DefaultItem.Count is the magazine count of this loaded weapon.
        fields = HOST.split(',')
        self.assertEqual(fields[6:10], ['1', '0', '15', '9'])
        fields[9] = '8'
        spent = ','.join(fields)
        old_lease = self.readback(HOST)
        self.guest.equipment = spent
        self.step(8)
        self.assertGreater(self.guest.link.serial, 0)
        self.assertEqual(self.guest.link.ack, self.guest.link.serial)
        self.assert_private(spent)

        self.disconnect()
        self.guest.link = GuestEquipmentLink(self.guest.data, self.guest.pid, b'G')
        self.guest.reader_run = 'rejoined-runtime'
        self.guest.equipment = HOST
        self.connect(2)
        self.assertNotEqual(self.readback(spent), old_lease)
        self.assertEqual(self.host.equipment, HOST)
        self.assert_private(spent)

    def test_first_join_private_updates_empty_inventory_and_rejoin_after_host_changes(self):
        self.guest.sample_changes['guest_account_id'] = SECOND_ACCOUNT
        first_lease = self.readback(HOST)
        first_restore = read(self.guest.data / RESTORE)
        self.assert_private(HOST)
        self.assertFalse(self.record(SECOND_ACCOUNT).exists())
        self.guest.equipment = AMMO
        self.step(3)
        self.assert_private(AMMO)
        self.host.equipment = EMPTY
        self.step(5)
        self.assert_private(AMMO)
        self.assertEqual(self.guest.equipment, AMMO)
        self.assertEqual(read(self.guest.data / RESTORE), first_restore)
        self.guest.equipment = EMPTY
        self.host.equipment = HOST
        self.step(3)
        self.assert_private(EMPTY)
        delayed = self.packet(first_lease, AMMO.encode())
        self.disconnect()
        self.connect(2)
        self.guest.equipment = HOST
        new_lease = self.readback(EMPTY)
        self.assertNotEqual(first_lease, new_lease)
        self.host.received.extend((delayed, self.packet(first_lease, AMMO.encode())))
        self.step(3)
        self.assert_private(EMPTY)

    def test_native_account_change_keeps_profiles_and_leases_separate(self):
        first = self.readback(HOST)
        self.guest.equipment = EMPTY
        self.step(3)
        self.disconnect()
        self.connect(2)
        self.host.native_changes['guest_account_id'] = SECOND_ACCOUNT
        self.host.equipment = AMMO
        second = self.readback(AMMO)
        self.assertNotEqual(second, first)
        self.host.received.append(self.packet(first, HOST.encode()))
        self.step(3)
        self.assert_private(EMPTY)
        self.assert_private(AMMO, SECOND_ACCOUNT)

    def test_guest_script_reload_after_lost_ack_restores_latest_personal_inventory(self):
        lease = self.readback(HOST)
        self.guest.equipment = AMMO
        self.step()
        # Commit the inventory on the host, but lose its response before the guest receives it.
        self.host.link.tick(self.host, self.handshake, self.host.source, self.host.received.popleft())
        self.guest.received.clear()
        self.assert_private(AMMO)
        # A REFramework script reload drops the Lua-side applied lease while the bridge stays connected.
        self.guest.lease = None
        self.guest.reader_run = 'second-runtime'
        self.step(3)
        command = read(self.guest.data / RESTORE)
        self.assertEqual(command['lease'], lease)
        self.assertEqual(command['reader_run'], 'second-runtime')
        self.assertEqual(command['equipment'], AMMO)
        self.guest.lease, self.guest.equipment = lease, command['equipment']
        self.step(6)
        self.assert_private(AMMO)
        self.assertEqual(self.guest.link.ack, self.guest.link.serial)

    def test_invalid_native_receipt_cannot_seed_first_join(self):
        for invalid in ({'game_pid': 999}, {'role': 'G'}, {'revision': 99}, {'guest_account_id': None},
                        {'snapshot_epoch': 'bb' * 8}, {'equipment_pose_epoch': self.guest.epoch.hex()},
                        {'at': int(self.clock.time()) - 10}):
            with self.subTest(invalid=invalid):
                self.host.native_changes = invalid
                self.step(2)
                self.assertFalse(self.record().exists())
                self.assertFalse((self.guest.data / RESTORE).exists())
        self.host.native_changes = {}
        self.readback(HOST)

    def test_unscoped_observation_does_not_overwrite_existing_guest(self):
        lease = self.readback(HOST)
        for invalid in ({'at': int(self.clock.time()) - 10}, {'revision': 0}, {'pid': 10000},
                        {'session': 'f' * 32}, {'namespace': 'b' * 32}):
            with self.subTest(invalid=invalid):
                self.host.sample_changes = invalid
                self.host.received.append(self.packet(lease, AMMO.encode()))
                self.step(2)
                self.assert_private(HOST)

    def test_matching_but_invalid_native_scope_cannot_seed_guest_record(self):
        invalid_scopes = ({'snapshot_epoch': ''}, {'snapshot_epoch': None}, {'revision': 0}, {'revision': True})
        for number, invalid in enumerate(invalid_scopes):
            with self.subTest(invalid=invalid):
                account = str(int(ACCOUNT) + number)
                self.host.sample_changes = invalid
                self.host.native_changes = {**invalid, 'guest_account_id': account}
                self.step()
                self.assertFalse(self.record(account).exists())

    def test_partial_malformed_and_out_of_order_chunks_do_not_replace_inventory(self):
        lease = self.readback(HOST)
        original = self.record().read_bytes()
        # Current native inventories fit one chunk. An oversized/malformed reconstruction,
        # arriving final chunk first, must leave the last usable record intact.
        first = b'E1,' + b'1' * (CHUNK - 3)
        for packet in (b'short', self.packet(lease, b'\xff'), self.packet(lease, b'1', index=1, count=2),
                       self.packet(lease, first, index=0, count=2)):
            with self.subTest(size=len(packet)):
                self.host.received.append(packet)
                self.step()
                self.assertEqual(self.record().read_bytes(), original)

    def test_numeric_but_incomplete_wire_cannot_replace_usable_equipment(self):
        lease = self.readback(HOST)
        self.host.received.append(self.packet(lease, b'E1,999'))
        self.step()
        self.assert_private(HOST)
