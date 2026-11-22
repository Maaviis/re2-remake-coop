from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from enemy_live import EnemyLiveFeed
from enemy_witness import EnemyStateFile, SCOPE, compare_enemy_snapshots
from load_witness import LoadStateFile, MAX_BYTES
from protocol.snapshot_transfer import snapshot_packets
from save_catalog import SaveCatalog
from steam_pose_bridge import SteamPipe
import steam_snapshot_transfer as transfer
from sync_model import state_digest
from tests.test_load_witness import sample as load_sample
from tests.test_save_catalog import source
from tests.test_steam_snapshot_transfer import EPOCH, NativePipePair, REQUEST, SESSION


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

    def capture(self, comparison_id=None):
        return EnemyStateFile(self.data).snapshot_for_load(
            self.request, self.reference, SESSION, comparison_id=comparison_id, now=100)

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

    def test_campaign_feed_requires_its_own_released_native_source(self):
        feed = EnemyLiveFeed(self.data, self.request, self.reference, campaign=True)
        observation = report()
        area = {'scenario': observation['state']['checkpoint']['scenario'], 'map': 4, 'area': 2}
        observation['state']['campaign_area'] = area
        observation['state']['entries'][0]['live']['is_live'] = True
        campaign_path = self.data / feed.reader.filename
        self.assertNotEqual(campaign_path, self.enemy_path)
        self.assertFalse(feed.poll(now=100)['available'])

        campaign_path.write_text(json.dumps(observation), encoding='utf-8')
        guard = {**self.guard, 'writes': {'save': 1}, 'protection_active': True, 'in_title': False,
                 'guard_run_id': 'guard-test', 'load_hold': {
                     'phase': 'released', 'native_phase': 'released', 'observed_at': 100,
                     'load_request_id': self.request, 'pause_id': self.request, 'guard_run_id': 'guard-test',
                 }}
        self.write(report(), guard=guard)
        self.assertEqual(feed.poll(now=100)['campaign_area'], area)
        with self.assertRaisesRegex(ValueError, 'no fresh scoped evidence'):
            self.capture()
        self.write(report(), guard={**guard, 'protection_active': False})
        self.assertFalse(feed.poll(now=100)['available'])

    def test_campaign_deaths_need_callback_and_a_consistent_later_native_state(self):
        feed = EnemyLiveFeed(self.data, self.request, self.reference, campaign=True, death_evidence=True)
        guard = {**self.guard, 'protection_active': True, 'in_title': False, 'guard_run_id': 'guard-test',
                 'load_hold': {'phase': 'released', 'native_phase': 'released', 'observed_at': 100,
                               'load_request_id': self.request, 'pause_id': self.request, 'guard_run_id': 'guard-test'}}
        self.write(report(), guard=guard)
        observation = report()
        state = observation['state']
        state.update(campaign_area={'scenario': 1, 'map': 12, 'area': 7}, campaign_visit='visit-1',
                     campaign_death_callbacks=None)
        row = state['entries'][0]
        row['kind_id'] = row['stored']['kind_id'] = 0
        row['live'].update(hp=0, is_dead=True, is_live=False)
        identity = row['id']
        path = self.data / feed.reader.filename

        def publish():
            path.write_text(json.dumps(observation), encoding='utf-8')
            result = feed.poll(now=100)
            observation['sequence'] += 1
            return result or feed.latest

        self.assertEqual(publish()['death_observations'], {}, 'zero HP and dead flag invented a returned callback')
        callbacks = state['campaign_death_callbacks'] = {identity: {'sequence': 1, 'at': 101}}
        self.assertEqual(publish()['death_observations'], {})
        callbacks[identity]['at'] = 96
        self.assertEqual(publish()['death_observations'], {})
        callbacks[identity]['at'] = 99
        row['live']['is_live'] = True
        self.assertEqual(publish()['death_observations'], {})
        row['live']['is_live'] = False
        matched = publish()['death_observations'][identity]
        self.assertTrue(matched['active'])
        self.assertEqual(matched['callback_sequence'], 1)
        self.assertEqual((matched['kind_id'], matched['hp'], matched['inherit_id']), (0, 0, -1))

        state['active_count'] = 0
        row['live'] = {'present': False}
        self.assertEqual(publish()['death_observations'], {})
        state['stored_entries'][0].update(kind_id=0, hp=0, eliminated=True)
        self.assertFalse(publish()['death_observations'][identity]['active'])
        state.update(campaign_visit='visit-2', campaign_death_callbacks={})
        self.assertEqual(publish()['death_observations'], {})
        state['campaign_death_callbacks'] = {identity: {'sequence': True, 'at': 99}}
        self.assertEqual(publish()['reason'], 'source_unavailable')

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
            self.assertEqual(guest.result(), self.capture(REQUEST))
            self.assertEqual(host.result(), 0)
        self.assertIn('Guest acknowledged', host_output.getvalue())

    def test_comparison_reports_identity_disagreements_per_source(self):
        host = self.capture(REQUEST)
        guest_report = report()
        guest_state = guest_report['state']
        first, second = guest_state['entries']
        first['live']['inherit_id'] = -3
        second['id'] = guid(4)
        guest_state['stored_entries'][1]['id'] = guid(5)
        self.write(guest_report)
        result = compare_enemy_snapshots(host, self.capture(REQUEST))
        self.assertEqual(result['sources']['registry'],
                         {'matched': 1, 'host_only': [guid(2)], 'guest_only': [guid(4)],
                          'identity_mismatches': []})
        self.assertEqual(result['sources']['live']['identity_mismatches'], [guid(1)])
        self.assertEqual(result['sources']['storage']['host_only'], [guid(3)])
        self.assertEqual(result['sources']['storage']['guest_only'], [guid(5)])
        self.assertEqual(result['sources']['stored_context']['matched'], 1)
        self.assertEqual(result['live_candidates'], [])

    def test_live_candidate_requires_active_observations_on_both_peers(self):
        host = self.capture(REQUEST)
        baseline = compare_enemy_snapshots(host, self.capture(REQUEST))
        self.assertEqual(baseline['live_candidates'], [guid(1)])
        guest_report = report()
        guest_report['state']['entries'][0]['live']['active'] = False
        guest_report['state']['active_count'] = 0
        self.write(guest_report)
        comparison = compare_enemy_snapshots(host, self.capture(REQUEST))
        self.assertEqual(comparison['sources']['live']['matched'], 1)
        self.assertEqual(comparison['sources']['active']['host_only'], [guid(1)])
        self.assertEqual(comparison['live_candidates'], [])

    def test_cannot_compare_a_different_transfer_or_a_generic_snapshot(self):
        host = self.capture(REQUEST)
        with self.assertRaisesRegex(ValueError, 'checkpoints or requests'):
            compare_enemy_snapshots(host, self.capture('f' * 32))
        with self.assertRaisesRegex(ValueError, 'unexpected native enemy fields'):
            compare_enemy_snapshots(host, self.capture())
        malformed = deepcopy(host)
        malformed['state']['enemies'][guid(1)]['registered']['id'] = guid(8)
        malformed['digest'] = state_digest(malformed['state'])
        with self.assertRaisesRegex(ValueError, 'peer enemy GUID does not match'):
            compare_enemy_snapshots(malformed, self.capture(REQUEST))

    def run_guest_comparison(self, host_snapshot, output):
        pipe = SteamPipe(123)
        packets = snapshot_packets(host_snapshot, REQUEST)
        self.assertEqual(len(packets), 1)
        pipe.request = Mock(side_effect=[b'G' + EPOCH, b'S', b'G' + EPOCH + packets[0], b'S'])
        arguments = ['steam_snapshot_transfer.py', '--role', 'guest', '--pid', '123',
                     '--data', str(self.data), '--file', str(output), '--native-enemies',
                     '--load-request-id', self.request, '--save-slot', 'scenario:4',
                     '--allow-save-date', self.save_date, '--session-id', SESSION, '--request-id', REQUEST]
        stdout, errors = io.StringIO(), io.StringIO()
        with (patch.object(transfer, 'SteamPipe', return_value=pipe),
              patch.object(transfer.time, 'time', return_value=100),
              patch.object(sys, 'argv', arguments), patch.object(sys, 'platform', 'win32'),
              redirect_stdout(stdout), redirect_stderr(errors)):
            result = transfer.main()
        return result, stdout.getvalue(), errors.getvalue(), pipe

    def test_guest_cli_confirms_and_saves_after_comparing_the_local_witness(self):
        host = self.capture(REQUEST)
        guest_report = report()
        guest_report.update(sequence=6, observed_at=99)
        guest_report['state']['entries'][0]['live']['hp'] = 13
        self.write(guest_report)
        output = self.data / 'peer-observation.json'
        code, stdout, errors, pipe = self.run_guest_comparison(host, output)
        self.assertEqual((code, errors), (0, ''))
        comparison = json.loads(stdout)
        self.assertEqual((comparison['host_sequence'], comparison['guest_sequence']), (9, 6))
        self.assertEqual(comparison['live_candidates'], [guid(1)])
        self.assertEqual(transfer._read_snapshot(output), host)
        self.assertEqual(pipe.request.call_args.args[0][-4:], b'\xff' * 4)

    def test_guest_cli_does_not_confirm_or_export_for_a_different_checkpoint(self):
        host = self.capture(REQUEST)
        guest_report, core = report(), load_sample()
        for value in (guest_report, core):
            value['state']['checkpoint']['save_guid'] = guid(7)
        self.write(guest_report, core=core)
        output = self.data / 'peer-observation.json'
        output.write_bytes(b'previous result')
        code, stdout, errors, pipe = self.run_guest_comparison(host, output)
        self.assertEqual((code, stdout), (1, ''))
        self.assertIn('different checkpoints or requests', errors)
        self.assertEqual(output.read_bytes(), b'previous result')
        self.assertEqual(pipe.request.call_count, 3)


if __name__ == '__main__':
    unittest.main()
