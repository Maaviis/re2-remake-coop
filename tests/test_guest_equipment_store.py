from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from guest_equipment_store import GuestEquipmentStore


EMPTY = {'equipment': 'E1,8,0,-1,-1,-1,0,0,0'}


def ammo(count):
    return {'equipment': f'E1,8,1,0,0,1,-1,0,0,{count},0,0,-1,-1,-1,0,0,0'}


class GuestEquipmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.solo = self.root / '123/883710/remote/win64_save'
        self.solo.mkdir(parents=True)
        self.namespace = 'a' * 32
        self.store = GuestEquipmentStore(self.solo, self.namespace)
        self.guest = '76561198012345678'
        self.host = ammo(31)

    def test_first_join_clones_host_and_restart_restores_guest_even_when_empty(self):
        lease, equipment = self.store.join(self.guest, self.host)
        self.assertEqual(equipment, self.host)
        equipment.update(ammo(0))
        self.assertEqual(self.host, ammo(31))
        self.store.save(self.guest, lease, equipment)
        restarted = GuestEquipmentStore(self.solo, self.namespace)
        new_lease, restored = restarted.join(int(self.guest), None)
        self.assertNotEqual(lease, new_lease)
        self.assertEqual(restored, ammo(0))
        restarted.save(self.guest, new_lease, EMPTY)
        self.assertEqual(restarted.join(self.guest, self.host)[1], EMPTY)
        self.assertEqual(list(self.solo.parent.iterdir()), [self.solo])
        self.assertEqual(list(self.solo.iterdir()), [])

    def test_schema_one_record_migrates_without_changing_owner_or_saved_equipment(self):
        from sync_model import state_digest
        from hashlib import sha256
        lease, _ = self.store.join(self.guest, self.host)
        account = sha256(self.guest.encode('ascii')).hexdigest()
        path = self.store.root / (account + '.json')
        path.write_text(json.dumps(dict(schema=1, lease=lease, equipment=self.host,
            digest=state_digest([self.namespace, account, lease, self.host]))))
        second, saved, profile, writer = self.store.join_with_history(self.guest, EMPTY)
        self.assertNotEqual(second, lease)
        self.assertEqual((saved, writer), (self.host, lease))
        self.store.save(self.guest, second, ammo(9))
        _, saved, same_profile, writer = self.store.join_with_history(self.guest, EMPTY)
        self.assertEqual((saved, same_profile, writer), (ammo(9), profile, second))

    def test_host_profiles_guests_and_campaigns_are_independent(self):
        lease, _ = self.store.join(self.guest, self.host)
        self.store.save(self.guest, lease, ammo(2))
        other_solo = self.root / '456/883710/remote/win64_save'
        other_solo.mkdir(parents=True)
        for store, guest in (
            (self.store, '76561198012345679'),
            (GuestEquipmentStore(self.solo, 'b' * 32), self.guest),
            (GuestEquipmentStore(other_solo, self.namespace), self.guest),
        ):
            with self.subTest(guest=guest, store=store):
                self.assertEqual(store.join(guest, ammo(10))[1], ammo(10))
                with self.assertRaises(ValueError):
                    store.save(guest, lease, ammo(300))
        self.assertEqual(self.store.join(self.guest, None)[1], ammo(2))
        for path in self.root.rglob('*'):
            self.assertNotIn(self.guest, path.name)
            if path.is_file():
                self.assertNotIn(self.guest.encode(), path.read_bytes())

    def test_concurrent_first_joins_seed_once_and_only_one_attachment_can_save(self):
        def attach(count):
            store = GuestEquipmentStore(self.solo, self.namespace)
            return store.join(self.guest, ammo(count))
        with ThreadPoolExecutor(max_workers=6) as pool:
            joins = list(pool.map(attach, range(6)))
        self.assertEqual(len({restore['equipment'] for _, restore in joins}), 1)
        self.assertEqual(len({lease for lease, _ in joins}), 6)
        accepted = []
        for index, (lease, _) in enumerate(joins):
            try:
                self.store.save(self.guest, lease, ammo(index))
            except ValueError:
                continue
            accepted.append(index)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(self.store.join(self.guest, self.host)[1], ammo(accepted[0]))

    def test_corruption_is_never_replaced_by_the_host_or_a_guest_save(self):
        lease, _ = self.store.join(self.guest, self.host)
        path, = self.root.rglob('*.json')
        original = path.read_bytes()
        mutated = json.loads(original)
        mutated['equipment'] = ammo(99)
        for damaged in (b'{', b'{}', b'null', json.dumps(mutated).encode()):
            path.write_bytes(damaged)
            for action in (lambda: self.store.join(self.guest, self.host),
                           lambda: self.store.save(self.guest, lease, EMPTY)):
                with self.assertRaises(ValueError):
                    action()
                self.assertEqual(path.read_bytes(), damaged)

    def test_invalid_snapshots_and_missing_records_cannot_overwrite_inventory(self):
        with self.assertRaises(ValueError):
            self.store.join(self.guest, None)
        with self.assertRaises(ValueError):
            self.store.save(self.guest, 'a' * 32, EMPTY)
        lease, _ = self.store.join(self.guest, EMPTY)
        for snapshot in ([], {}, {1: 'slot'}, {**EMPTY, 'extra': True}, {'equipment': 'E1,8,0'},
                         {'equipment': EMPTY['equipment'] + ',0' * 8193}):
            with self.subTest(snapshot_type=type(snapshot)), self.assertRaises(ValueError):
                self.store.save(self.guest, lease, snapshot)
        self.assertEqual(self.store.join(self.guest, self.host)[1], EMPTY)

    def test_stale_attachment_cannot_overwrite_a_newer_connection(self):
        first, _ = self.store.join(self.guest, self.host)
        restarted = GuestEquipmentStore(self.solo, self.namespace)
        current, _ = restarted.join(self.guest, self.host)
        restarted.save(self.guest, current, ammo(1))
        with self.assertRaises(ValueError):
            self.store.save(self.guest, first, self.host)
        self.assertEqual(self.store.join(self.guest, self.host)[1], ammo(1))
