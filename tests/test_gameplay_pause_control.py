from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gameplay_pause_control import CLOCKS, read_status, submit, wait_for_result
from tests.test_inventory_witness import detailed_sample
from tests.test_save_catalog import source


def status():
    return {'schema': 1, 'source': 're2', 'tdb': 70, 'scope': 'native_gameplay_pause',
            'run_id': 'pause-test', 'sequence': 1, 'observed_at': 100, 'pause_id': '',
            'phase': 'idle', 'available': True, 'reason': '', 'command_id': '', 'command_error': '',
            'release_id': '', 'clocks': {key: '0' for key in CLOCKS}}


class GameplayPauseControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.clock = patch('gameplay_pause_control.time.time', return_value=100)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.path = self.data / 're2_coop_gameplay_pause.json'
        self.command = self.data / 're2_coop_pause_command.json'
        self.load_id = 'a' * 32
        self.guard = {'schema': 1, 'at': 100, 'active': True, 'hooks': 26, 'load_request_id': self.load_id,
                      'policy_id': self.load_id, 'load_phase': 'scene_loaded', 'load_error': '',
                      'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4,
                      'allowed_load_calls': 1, 'denied_loads': 0, 'writes': None, 'has_player': True}
        self.write('re2_coop_gameplay_pause.json', status())
        self.write('re2_coop_save_guard.json', self.guard)
        self.write('re2_coop_inventory_state.json', detailed_sample())
        self.write('re2_coop_save_catalog.json', source())

    def write(self, name, value):
        (self.data / name).write_text(json.dumps(value))

    def test_pause_requires_fresh_native_inventory_evidence_for_the_permitted_loaded_save(self):
        command_id = submit(self.data, 'pause', load_id=self.load_id, allow_date='2026-11-11', seconds=7)
        command = json.loads(self.command.read_text())
        self.assertEqual(command, {'schema': 1, 'id': command_id, 'at': 100, 'action': 'pause',
                                   'load_request_id': self.load_id, 'seconds': 7})
        before = self.command.read_bytes()
        for fields in ({'load_id': 'b' * 32}, {'allow_date': '2026-11-12'}, {'seconds': True}, {'seconds': 16}):
            arguments = {'load_id': self.load_id, 'allow_date': '2026-11-11', 'seconds': 7, **fields}
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                submit(self.data, 'pause', **arguments)
            self.assertEqual(self.command.read_bytes(), before)
        self.guard['policy_id'] = 'c' * 32
        self.write('re2_coop_save_guard.json', self.guard)
        with self.assertRaises(ValueError): submit(self.data, 'pause', load_id=self.load_id, allow_date='2026-11-11')
        self.assertEqual(self.command.read_bytes(), before)

    def test_missing_stale_or_already_active_source_never_queues_a_new_pause(self):
        for change in ('missing_inventory', 'stale_inventory', 'active_pause', 'guard_write', 'guard_denied'):
            value = detailed_sample()
            self.write('re2_coop_inventory_state.json', value)
            self.write('re2_coop_gameplay_pause.json', status())
            guard = deepcopy(self.guard)
            if change == 'missing_inventory': (self.data / 're2_coop_inventory_state.json').unlink()
            elif change == 'stale_inventory':
                value['observed_at'] = 96; self.write('re2_coop_inventory_state.json', value)
            elif change == 'active_pause': self.write('re2_coop_gameplay_pause.json', {**status(), 'phase': 'held', 'pause_id': 'd' * 32})
            elif change == 'guard_write': guard['writes'] = {'save': 1}
            else: guard['denied_loads'] = 1
            self.write('re2_coop_save_guard.json', guard)
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)):
                submit(self.data, 'pause', load_id=self.load_id, allow_date='2026-11-11')
            self.assertFalse(self.command.exists())

    def test_owned_return_still_works_when_clock_measurement_is_unavailable(self):
        owned = 'd' * 32
        held = {**status(), 'phase': 'held', 'pause_id': owned, 'available': False,
                'reason': 'clock_unavailable', 'clocks': None}
        self.write('re2_coop_gameplay_pause.json', held)
        with self.assertRaises(ValueError): submit(self.data, 'return', pause_id='e' * 32)
        self.assertFalse(self.command.exists())
        command_id = submit(self.data, 'return', pause_id=owned)
        self.assertEqual(json.loads(self.command.read_text())['pause_id'], owned)
        self.assertNotEqual(command_id, owned)

    def test_wait_binds_pause_and_return_results_despite_a_different_rejected_command(self):
        owned, release = 'd' * 32, 'e' * 32
        held = {**status(), 'phase': 'held', 'pause_id': owned, 'command_id': 'f' * 32,
                'command_error': 'pause_in_progress'}
        with patch('gameplay_pause_control.read_status', side_effect=[ValueError('partial'), held]), \
                patch('gameplay_pause_control.time.sleep'), \
                patch('gameplay_pause_control.time.monotonic', side_effect=[10, 10.1, 10.2]):
            self.assertEqual(wait_for_result(self.data, owned, action='pause')['pause_id'], owned)
        released = {**held, 'phase': 'released', 'release_id': release}
        unrelated = {**released, 'release_id': 'deadline'}
        with patch('gameplay_pause_control.read_status', side_effect=[unrelated, released]) as reader, \
                patch('gameplay_pause_control.time.sleep'), \
                patch('gameplay_pause_control.time.monotonic', side_effect=[10, 10.1, 10.2]):
            self.assertEqual(wait_for_result(self.data, release, action='return', pause_id=owned)['release_id'], release)
            self.assertEqual(reader.call_count, 2)
        with patch('gameplay_pause_control.time.monotonic', side_effect=[10, 11]):
            with self.assertRaises(TimeoutError): wait_for_result(self.data, owned, action='pause', timeout=.1)

    def test_invalid_status_and_unsigned_clock_shapes_are_rejected(self):
        for change in ('old', 'future', 'bool', 'scope', 'phase', 'reason', 'clock_overflow', 'clock_missing', 'clock_float'):
            value = status()
            if change == 'old': value['observed_at'] = 96
            elif change == 'future': value['observed_at'] = 101
            elif change == 'bool': value['available'] = 1
            elif change == 'scope': value['scope'] = 'complete_world'
            elif change == 'phase': value['phase'] = 'requesting'
            elif change == 'reason': value['reason'] = 'read_failed'
            elif change == 'clock_overflow': value['clocks']['get_InSceneTime'] = str(2**64)
            elif change == 'clock_missing': del value['clocks']['get_InSceneTime']
            else: value['clocks']['get_InSceneTime'] = '1.0'
            self.write('re2_coop_gameplay_pause.json', value)
            with self.subTest(change=change), self.assertRaises(ValueError): read_status(self.data)
