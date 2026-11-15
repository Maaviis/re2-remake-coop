from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inventory_witness import InventoryStateFile, SCOPE
from load_witness import LoadStateFile
from save_catalog import SaveCatalog
from tests.test_load_witness import sample
from tests.test_save_catalog import source


def detail_slot(slot):
    result = deepcopy(slot)
    if result == {'present': False}:
        return result
    primitive = {'present': True, 'item_id': 0, 'weapon_type': 9, 'weapon_parts': 0, 'bullet_id': 15, 'number': 4}
    extra = {'present': True, 'uint_data': 2**32 - 1, 'item_id': 0,
             'rogue_weapon_level': 0, 'initial_set': False, 'initial_count': 0}
    result.update(last_weapon_type=9, inner=deepcopy(primitive), extra=deepcopy(extra), stock={
        'present': True, 'index': 0, 'weapon_equipped': False, 'default_item': deepcopy(primitive),
        'additional_item': {**primitive, 'weapon_type': -1, 'number': 1}, 'extra': deepcopy(extra)})
    return result


def detailed_sample():
    value = sample()
    value['scope'] = SCOPE
    inventory = value['state']['inventory']
    inventory['slots'] = [detail_slot(slot) for slot in inventory['slots']]
    inventory['equipped'] = {name: detail_slot(slot) for name, slot in inventory['equipped'].items()}
    inventory['shortcuts'] = {
        'main': {'count': 2, 'entries': [{'key': 0, 'slot': detail_slot(inventory['slots'][0])},
                                        {'key': 3, 'slot': detail_slot(inventory['slots'][1])}]},
        'sub': {'count': 0, 'entries': None}}
    return value


class InventoryWitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.path = self.data / InventoryStateFile.filename
        self.reader = InventoryStateFile(self.data)
        catalog = self.data / 'catalog.json'
        catalog.write_text(json.dumps(source()))
        self.reference = SaveCatalog(catalog, allow_date='2026-11-11').snapshot(now=100)['entries'][0]['reference']
        self.request_id = 'a' * 32
        self.guard = {'schema': 1, 'at': 100, 'active': True, 'hooks': 26, 'load_request_id': self.request_id,
                      'policy_id': self.request_id, 'load_phase': 'scene_loaded', 'load_error': '',
                      'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4,
                      'allowed_load_calls': 1, 'denied_loads': 0, 'writes': None}
        self.write(detailed_sample())

    def write(self, value):
        self.path.write_text(json.dumps(value))
        (self.data / 're2_coop_save_guard.json').write_text(json.dumps(self.guard))

    def test_details_bind_to_the_original_guarded_load_with_separate_scope(self):
        result = self.reader.for_load(self.request_id, self.reference, now=100)
        self.assertEqual(result['scope'], SCOPE)
        slot = result['state']['inventory']['slots'][0]
        self.assertEqual(slot['stock']['additional_item']['number'], 1)
        self.assertEqual(slot['stock']['default_item']['number'], 4)
        self.assertEqual(slot['extra']['uint_data'], 2**32 - 1)
        self.assertIs(slot['extra']['initial_set'], False)
        self.assertEqual(result['state']['inventory']['shortcuts']['sub']['entries'], [])
        for change in ('payload', 'shortcut'):
            value = detailed_sample()
            if change == 'payload':
                value['state']['inventory']['slots'][0]['stock']['additional_item']['number'] = 2
            else:
                value['state']['inventory']['shortcuts']['main']['entries'][1]['key'] = 2
            value['sequence'] = 2
            self.write(value)
            changed = InventoryStateFile(self.data).for_load(self.request_id, self.reference, now=100)
            self.assertNotEqual(changed['evidence_digest'], result['evidence_digest'])
        self.guard['policy_id'] = 'b' * 32
        self.write(detailed_sample())
        with self.assertRaises(ValueError):
            InventoryStateFile(self.data).for_load(self.request_id, self.reference, now=100)

    def test_core_and_detail_readers_do_not_accept_each_others_scope(self):
        (self.data / LoadStateFile.filename).write_text(json.dumps(detailed_sample()))
        with self.assertRaises(ValueError):
            LoadStateFile(self.data).read(now=100)
        self.write(sample())
        with self.assertRaises(ValueError):
            self.reader.read(now=100)

    def test_malformed_or_missing_payloads_never_become_valid_details(self):
        for change in ('missing', 'unknown', 'bool', 'unsigned', 'negative_unsigned', 'float', 'stock', 'absent', 'slot_unknown'):
            value = detailed_sample()
            slot = value['state']['inventory']['slots'][0]
            if change == 'missing': del slot['stock']['additional_item']
            elif change == 'unknown': slot['inner']['runtime_pointer'] = 1234
            elif change == 'bool': slot['extra']['initial_set'] = 0
            elif change == 'unsigned': slot['extra']['uint_data'] = 2**32
            elif change == 'negative_unsigned': slot['extra']['uint_data'] = -1
            elif change == 'float': slot['stock']['default_item']['number'] = 1.0
            elif change == 'stock': slot['stock']['weapon_equipped'] = 0
            elif change == 'absent': slot['stock'] = {'present': 0}
            else: slot['runtime_pointer'] = 1
            self.write(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                InventoryStateFile(self.data).read(now=100)
        value = detailed_sample()
        value['state']['inventory']['slots'][0].update(stock={'present': False}, inner={'present': False})
        self.write(value)
        self.assertFalse(InventoryStateFile(self.data).read(now=100)['state']['inventory']['slots'][0]['stock']['present'])

    def test_shortcut_keys_must_be_known_unique_ordered_and_counted(self):
        for change in ('count', 'duplicate', 'order', 'unknown', 'bool', 'nil', 'absent', 'missing_detail', 'extra_group'):
            value = detailed_sample()
            shortcuts = value['state']['inventory']['shortcuts']
            group = shortcuts['main']
            if change == 'count': group['count'] = 3
            elif change == 'duplicate': group['entries'][1]['key'] = 0
            elif change == 'order': group['entries'].reverse()
            elif change == 'unknown': group['entries'][1]['key'] = 4
            elif change == 'bool': group['entries'][0]['key'] = False
            elif change == 'nil': group['entries'] = None
            elif change == 'absent': group['entries'][0]['slot'] = {'present': False}
            elif change == 'missing_detail': del group['entries'][0]['slot']['stock']
            else: shortcuts['third'] = {'count': 0, 'entries': []}
            self.write(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                InventoryStateFile(self.data).read(now=100)

    def test_loss_staleness_changed_sequence_and_vm_restart_do_not_reuse_old_details(self):
        value = detailed_sample()
        self.reader.for_load(self.request_id, self.reference, now=100)
        value['state']['inventory']['shortcuts']['main']['entries'][0]['slot']['extra']['uint_data'] = 0
        self.write(value)
        with self.assertRaises(ValueError): self.reader.read(now=100)
        value = detailed_sample()
        value.update(sequence=2, available=False, reason='state_read_failed')
        del value['state']
        self.write(value)
        self.assertFalse(self.reader.read(now=100)['available'])
        with self.assertRaises(ValueError): self.reader.for_load(self.request_id, self.reference, now=100)
        self.write(detailed_sample())
        with self.assertRaises(ValueError): InventoryStateFile(self.data).read(now=104)
        value = detailed_sample(); value['run_id'] = 'new-vm'
        self.write(value)
        with self.assertRaises(ValueError): self.reader.for_load(self.request_id, self.reference, now=100)
