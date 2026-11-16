from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from enemy_witness import EnemyStateFile, SCOPE
from load_witness import LoadStateFile, MAX_BYTES
from save_catalog import SaveCatalog
import steam_snapshot_transfer as transfer
from tests.test_load_witness import sample as load_sample
from tests.test_save_catalog import source
from tests.test_steam_snapshot_transfer import NativePipePair, REQUEST, SESSION


def guid(number):
    return f'{number:08x}-ffff-abcd-f0f1-f2f3f4f5f6f7'


def rows():
    transform = {'position': [0.125, 0, -3.0], 'rotation': [0, 0, 0, 1]}
    stored = {'present': True, 'id': guid(1), 'kind_id': 4, 'inherit_id': -1, 'default_hp': 101,
              'hp': 17, 'wince_hp': 2, 'eliminated': False, 'flags': 0xffffffff, 'map': 12,
              'area': 7, **transform}
    first = {'id': guid(1), 'kind_id': 4, 'stored': stored,
             'context': {'present': True, 'inherit_id': -1, 'status': 4, 'eliminated': False, **transform},
             'live': {'present': True, 'inherit_id': -1, 'hp': 7, 'default_hp': 100, 'is_dead': False,
                      'is_live': False, 'active': True, 'setup': True, 'loading': False, 'standby': False,
                      'conditions': 0xffffffff, 'conditions2': 9}}
    second = {**first, 'id': guid(2), 'stored': {'present': False}, 'live': {'present': False}}
    storage = [{**stored, 'hp': 32}, {**stored, 'id': guid(3), 'hp': 0}]
    return [first, second], storage


def report():
    registered, storage = rows()
    checkpoint = load_sample()['state']['checkpoint']
    return {
        'schema': 1, 'source': 're2', 'tdb': 70, 'scope': SCOPE, 'available': True, 'reason': 'ok',
        'run_id': 'private-enemy-vm', 'sequence': 9, 'observed_at': 100,
        'state': {'checkpoint': {key: checkpoint[key] for key in ('game_guid', 'save_guid', 'scenario', 'location')},
                  'registered_count': 2, 'active_count': 1, 'stored_count': 2,
                  'paused': False, 'total_kills': 0xffffffff, 'entries': registered, 'stored_entries': storage},
    }


class EnemyWitnessTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        self.enemy_path = self.data / EnemyStateFile.filename
        self.core_path = self.data / LoadStateFile.filename
        self.request = 'd' * 32
        self.save_date = '2026-11-11'
        self.guard_path = self.data / 're2_coop_save_guard.json'
        self.guard = {'schema': 1, 'at': 100, 'active': True, 'hooks': 26, 'load_request_id': self.request,
                      'policy_id': self.request, 'load_phase': 'scene_loaded', 'load_error': '',
                      'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4,
                      'allowed_load_calls': 1, 'denied_loads': 0, 'writes': None}
        catalog = self.data / 're2_coop_save_catalog.json'
        catalog.write_text(json.dumps(source()), encoding='utf-8')
        self.reference = SaveCatalog(catalog, allow_date=self.save_date).snapshot(now=100)['entries'][0]['reference']
        self.write(report())

    def write(self, observation, *, core=None, guard=None):
        self.enemy_path.write_text(json.dumps(observation, indent=2), encoding='utf-8')
        self.core_path.write_text(json.dumps(load_sample() if core is None else core), encoding='utf-8')
        self.guard_path.write_text(json.dumps(self.guard if guard is None else guard), encoding='utf-8')

    def capture(self):
        return EnemyStateFile(self.data).snapshot_for_load(self.request, self.reference, SESSION, now=100)

    def test_sources_remain_distinct_and_no_native_save_identifiers_leave_the_host(self):
        snapshot = self.capture()
        self.assertEqual(snapshot['sequence'], 9)
        self.assertEqual(snapshot['session_id'], SESSION)
        enemies = snapshot['state']['enemies']
        self.assertEqual(set(enemies), {guid(1), guid(2), guid(3)})
        first = enemies[guid(1)]
        self.assertEqual((first['registered']['live']['hp'], first['registered']['stored']['hp'],
                          first['storage']['hp']), (7, 17, 32))
        self.assertFalse(first['registered']['live']['is_dead'])
        self.assertEqual(first['registered']['live']['conditions'], 0xffffffff)
        self.assertEqual(first['storage']['inherit_id'], -1)
        self.assertEqual(enemies[guid(2)]['registered']['live'], {'present': False})
        self.assertEqual(set(enemies[guid(3)]), {'storage'})
        self.assertFalse(enemies[guid(3)]['storage']['eliminated'])
        self.assertEqual(enemies[guid(3)]['storage']['hp'], 0)
        metadata = snapshot['state']['flags']['native_enemy_observation']
        self.assertEqual((metadata['scope'], metadata['active_count'], metadata['total_kills']), (SCOPE, 1, 0xffffffff))
        encoded = json.dumps(snapshot)
        self.assertNotIn(load_sample()['state']['checkpoint']['save_guid'], encoded)
        self.assertNotIn(load_sample()['state']['checkpoint']['game_guid'], encoded)
        self.assertNotIn(self.request, encoded)
        self.assertNotIn('private-enemy-vm', encoded)

    def test_inactive_empty_registry_is_valid_but_unavailable_source_is_not(self):
        value = report()
        value['state'].update(entries=None, registered_count=0, active_count=0, stored_entries=None, stored_count=0)
        self.write(value)
        self.assertEqual(self.capture()['state']['enemies'], {})
        value.update(available=False, reason='scene_unavailable', state=None)
        self.write(value)
        with self.assertRaisesRegex(ValueError, 'no fresh scoped evidence'):
            self.capture()

    def test_rejects_stale_sample_unrelated_load_and_different_checkpoint(self):
        value = report()
        for stamp in (96, 101):
            with self.subTest(stamp=stamp):
                self.write({**value, 'observed_at': stamp})
                with self.assertRaisesRegex(ValueError, 'expired native evidence'):
                    self.capture()
        self.write(value, guard={**self.guard, 'load_started_at': 100})
        with self.assertRaisesRegex(ValueError, 'no fresh scoped evidence'):
            self.capture()
        for field, mismatch in (('save_guid', guid(7)), ('game_guid', guid(8)), ('location', 17)):
            changed = deepcopy(value)
            changed['state']['checkpoint'][field] = mismatch
            self.write(changed)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'different native checkpoint'):
                self.capture()
        self.write(value, core={**load_sample(), 'observed_at': 96})
        with self.assertRaisesRegex(ValueError, 'expired native evidence'):
            self.capture()

    def test_rejects_malformed_rows_even_under_a_valid_load_receipt(self):
        for change in ('duplicate', 'unordered', 'wrong count', 'active count', 'stored identity',
                       'empty GUID', 'inactive HP', 'zero rotation', 'NaN', 'false HP', 'legacy scope'):
            observation = report()
            state = observation['state']
            first, second = state['entries']
            if change == 'duplicate':
                state['entries'][1] = first
            elif change == 'unordered':
                state['entries'].reverse()
            elif change == 'wrong count':
                state['stored_count'] = 513
            elif change == 'active count':
                state['active_count'] = 2
            elif change == 'stored identity':
                first['stored']['id'] = guid(7)
            elif change == 'empty GUID':
                state['stored_entries'][0]['id'] = '00000000-0000-0000-0000-000000000000'
            elif change == 'inactive HP':
                second['live']['hp'] = 0
            elif change == 'zero rotation':
                first['context']['rotation'] = [0] * 4
            elif change == 'NaN':
                first['stored']['position'] = [0, 0, float('nan')]
            elif change == 'false HP':
                first['live']['hp'] = False
            else:
                observation['scope'] = 'registered_enemy_contexts'
            self.write(observation)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.capture()

    def test_read_is_bounded_and_rejects_partial_or_duplicate_json(self):
        self.enemy_path.write_text(' ' * (EnemyStateFile.max_bytes + 1), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.capture()
        self.enemy_path.write_text('{"schema":1,', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.capture()
        self.enemy_path.write_text(json.dumps(report()).replace('"schema": 1', '"schema": 2, "schema": 1'),
                                   encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            self.capture()

    def test_native_cli_captures_large_observation_at_first_pull(self):
        value = report()
        state = value['state']
        first = state['entries'][0]
        registry = []
        for index in range(1, 257):
            item = deepcopy(first)
            item['id'] = item['stored']['id'] = guid(index)
            registry.append(item)
        state.update(entries=registry, registered_count=len(registry), active_count=len(registry))
        pair = NativePipePair()
        host_pipe = pair.pipe(b'H')
        original_request = host_pipe.request
        waiting = Event()

        def watch_request(command):
            if command == b'R':
                waiting.set()
            return original_request(command)

        host_pipe.request = watch_request
        host_args = ['steam_snapshot_transfer.py', '--role', 'host', '--pid', '123',
                     '--data', str(self.data), '--native-enemies', '--load-request-id', self.request,
                     '--save-slot', 'scenario:4', '--allow-save-date', self.save_date]
        self.enemy_path.unlink()
        host_output = io.StringIO()
        with (patch.object(transfer, 'SteamPipe', return_value=host_pipe),
              patch.object(transfer.secrets, 'token_hex', side_effect=[SESSION, REQUEST]),
              patch.object(transfer.time, 'time', return_value=100),
              patch.object(transfer, 'TIMEOUT', 4),
              patch.object(sys, 'argv', host_args), patch.object(sys, 'platform', 'win32'),
              redirect_stdout(host_output), ThreadPoolExecutor(max_workers=2) as executor):
            host = executor.submit(transfer.main)
            self.assertTrue(waiting.wait(2))
            self.write(value)
            self.assertGreater(self.enemy_path.stat().st_size, MAX_BYTES)
            guest = executor.submit(transfer.transfer, pair.pipe(b'G'), b'G', SESSION, REQUEST)
            self.assertEqual(guest.result(), self.capture())
            self.assertEqual(host.result(), 0)
        self.assertIn('Guest acknowledged', host_output.getvalue())


if __name__ == '__main__':
    unittest.main()
