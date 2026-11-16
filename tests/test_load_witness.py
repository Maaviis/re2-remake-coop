from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from load_witness import LoadStateFile, SCOPE
from save_catalog import SaveCatalog
from sync_model import state_digest
from tests.test_save_catalog import source


def slot():
    return {'present': True, 'stock_index': 0, 'slot_type': 1, 'item_id': -1, 'weapon_type': 9,
            'weapon_parts': 0, 'bullet_id': 2, 'number': 6, 'has_stock': True, 'blank': False,
            'force_blank': False, 'fat_slot': False, 'dead_slot': False, 'infinite': False}


def sample():
    return {'schema': 1, 'source': 're2', 'tdb': 70, 'run_id': 'native-test', 'sequence': 1,
            'observed_at': 100, 'scope': SCOPE, 'available': True, 'reason': 'ok', 'state': {
                'checkpoint': {'scenario': 1, 'survivor': 1, 'difficulty': 1, 'location': 16, 'saved_map': 350,
                               'game_guid': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
                               'save_guid': '12345678-1234-5678-90ab-cdef12345678'},
                'inventory': {'survivor': 1, 'role': 0, 'capacity': 1, 'slot_count': 2,
                              'slots': [slot(), {**slot(), 'stock_index': 1, 'fat_slot': True}],
                              'equipped': {'main': slot(), 'sub': {'present': False}, 'personal': {'present': False}}}}}


class LoadWitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.path = self.data / 're2_coop_load_state.json'
        self.guard_path = self.data / 're2_coop_save_guard.json'
        self.reader = LoadStateFile(self.data)
        self.request_id = 'a' * 32
        catalog = self.data / 'catalog.json'
        catalog.write_text(json.dumps(source()))
        self.reference = SaveCatalog(catalog, allow_date='2026-11-11').snapshot(now=100)['entries'][0]['reference']
        self.guard = {'schema': 1, 'at': 100, 'active': True, 'hooks': 26, 'load_request_id': self.request_id,
                      'policy_id': self.request_id, 'load_phase': 'scene_loaded', 'load_error': '',
                      'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4,
                      'allowed_load_calls': 1, 'denied_loads': 0, 'writes': None,
                      'command_id': 'b' * 32, 'command_error': 'load_in_progress'}
        self.write(sample())

    def write(self, value, guard=None):
        self.path.write_text(json.dumps(value))
        self.guard_path.write_text(json.dumps(self.guard if guard is None else guard))

    def test_binds_scoped_native_state_to_original_load_despite_a_different_rejected_command(self):
        evidence = self.reader.for_load(self.request_id, self.reference, now=100)
        self.assertEqual(evidence['scope'], SCOPE)
        self.assertEqual(evidence['evidence_digest'], state_digest(sample()['state']))
        self.assertEqual(evidence['state']['inventory']['slot_count'], 2)
        self.assertEqual(evidence['state']['inventory']['capacity'], 1)
        self.assertFalse(evidence['state']['inventory']['slots'][0]['blank'])
        evidence['state']['inventory']['slots'][0]['number'] = 99
        self.assertEqual(self.reader.accepted['state']['inventory']['slots'][0]['number'], 6)

    def test_stale_future_preload_other_slot_and_superseded_policy_never_attest(self):
        for fields in ({'at': 96}, {'at': 101}, {'load_started_at': 100}, {'load_started_at': 101},
                       {'load_started_at': 1}, {'load_request_id': 'c' * 32}, {'policy_id': 'c' * 32},
                       {'load_index': 3}, {'allowed_slot': 3}, {'load_phase': 'loading'},
                       {'load_error': 'native_load_error'}, {'denied_loads': 1}, {'writes': {'save': 1}},
                       {'allowed_load_calls': True}, {'hooks': 25}):
            value, guard, now = sample(), {**self.guard, **fields}, 100
            if fields == {'load_started_at': 1}:
                value['observed_at'], guard['at'], now = 222, 222, 222
            self.write(value, guard)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                LoadStateFile(self.data).for_load(self.request_id, self.reference, now=now)

    def test_source_and_shape_failures_never_become_a_complete_world_digest(self):
        for field, value in (('tdb', 71), ('source', 'fixture'), ('scope', 'complete_world'),
                             ('sequence', True), ('observed_at', 96), ('observed_at', 101)):
            bad = sample(); bad[field] = value
            self.write(bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.reader.read(now=100)
        for change in ('quantity', 'false_integer', 'absent_integer', 'missing_field', 'count', 'guid', 'scenario'):
            bad = sample()
            if change == 'quantity': bad['state']['inventory']['slots'][0]['number'] = float('nan')
            elif change == 'false_integer': bad['state']['inventory']['slots'][0]['blank'] = 0
            elif change == 'absent_integer': bad['state']['inventory']['equipped']['sub']['present'] = 0
            elif change == 'missing_field': del bad['state']['inventory']['slots'][0]['bullet_id']
            elif change == 'count': bad['state']['inventory']['slot_count'] = 1
            elif change == 'guid': bad['state']['checkpoint']['save_guid'] = 'pointer:1234'
            else: bad['state']['checkpoint']['scenario'] = 2
            self.write(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.reader.for_load(self.request_id, self.reference, now=100)

    def test_unavailable_partial_or_oversized_input_does_not_reuse_a_good_sample(self):
        self.reader.read(now=100)
        unavailable = {key: value for key, value in sample().items() if key != 'state'}
        unavailable.update(sequence=2, available=False, reason='scene_unavailable')
        self.write(unavailable)
        self.assertFalse(self.reader.read(now=100)['available'])
        with self.assertRaises(ValueError):
            self.reader.for_load(self.request_id, self.reference, now=100)
        self.path.write_text('{')
        with self.assertRaises(ValueError): self.reader.read(now=100)
        self.path.write_text(' ' * 131073)
        with self.assertRaises(ValueError): self.reader.read(now=100)

    def test_sequence_and_same_load_run_are_bound(self):
        self.reader.for_load(self.request_id, self.reference, now=100)
        bad = sample(); bad['state']['inventory']['slots'][0]['number'] += 1
        self.write(bad)
        with self.assertRaises(ValueError): self.reader.read(now=100)
        good = sample(); good['sequence'] = 2
        self.write(good); self.reader.read(now=100)
        self.write(sample())
        with self.assertRaises(ValueError): self.reader.read(now=100)
        good.update(run_id='new-vm', sequence=1)
        self.write(good)
        with self.assertRaises(ValueError): self.reader.for_load(self.request_id, self.reference, now=100)
        self.request_id = 'd' * 32
        self.guard.update(load_request_id=self.request_id, policy_id=self.request_id)
        self.write(good)
        self.assertEqual(self.reader.for_load(self.request_id, self.reference, now=100)['observer_run_id'], 'new-vm')

    def test_continuation_requires_a_verified_load_and_preserves_its_identity(self):
        with self.assertRaisesRegex(ValueError, 'previously verified'):
            self.reader.for_load(self.request_id, self.reference, now=100, continuing=True)
        self.reader.for_load(self.request_id, self.reference, now=100)
        value = sample(); value.update(sequence=2, observed_at=730)
        guard = {**self.guard, 'at': 730}
        self.write(value, guard)
        self.assertEqual(self.reader.for_load(self.request_id, self.reference, now=730,
                                             continuing=True)['observed_at'], 730)
        for changed in ('run', 'started_at', 'load_calls', 'checkpoint', 'reference'):
            candidate, changed_guard, reference = deepcopy(value), deepcopy(guard), deepcopy(self.reference)
            if changed == 'run': candidate['run_id'] = 'replaced-vm'
            elif changed == 'started_at': changed_guard['load_started_at'] = 97
            elif changed == 'load_calls': changed_guard['allowed_load_calls'] = 2
            elif changed == 'checkpoint': candidate['state']['checkpoint']['location'] = 17
            else: reference['metadata_digest'] = 'a' * 64
            candidate['sequence'] = 3
            self.write(candidate, changed_guard)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.reader.for_load(self.request_id, reference, now=730, continuing=True)

    def test_continuation_rejects_stale_guards_saves_and_time_rollback(self):
        self.reader.for_load(self.request_id, self.reference, now=100)
        value = sample(); value.update(sequence=2, observed_at=730)
        guard = {**self.guard, 'at': 730}
        for fields in ({'at': 726}, {'denied_loads': 1}, {'writes': {'autosave': 1}},
                       {'policy_id': 'e' * 32}, {'load_request_id': 'e' * 32}, {'allowed_slot': 3}):
            self.write(value, {**guard, **fields})
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.reader.for_load(self.request_id, self.reference, now=730, continuing=True)
        self.write(value, guard)
        self.reader.for_load(self.request_id, self.reference, now=730, continuing=True)
        value.update(sequence=3, observed_at=729)
        self.write(value, {**guard, 'at': 729})
        with self.assertRaisesRegex(ValueError, 'clock moved backwards'):
            self.reader.for_load(self.request_id, self.reference, now=729, continuing=True)

    def test_empty_native_sequence_and_zero_checkpoint_identity(self):
        value = sample()
        value['state']['inventory'].update(capacity=0, slot_count=0, slots=None)
        self.write(value)
        self.assertEqual(self.reader.read(now=100)['state']['inventory']['slots'], [])
        value['state']['checkpoint']['save_guid'] = '00000000-0000-0000-0000-000000000000'
        value['sequence'] = 2
        self.write(value)
        with self.assertRaises(ValueError): self.reader.for_load(self.request_id, self.reference, now=100)
