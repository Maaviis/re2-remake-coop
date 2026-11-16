from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lobby_sync import write_json
from prepared_checkpoint import PreparedCheckpoint, SCOPE
from save_catalog import SaveCatalog
import steam_snapshot_transfer as transfer
from sync_model import state_digest
from tests.test_load_witness import sample
from tests.test_save_catalog import source
from tests.test_steam_snapshot_transfer import NativePipePair, REQUEST, SESSION


class PreparedCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch('load_witness.time.time', return_value=100).start()

    def fixture(self, role):
        data = self.directory / role
        data.mkdir()
        catalog = data / 'catalog.json'
        write_json(catalog, source())
        reference = SaveCatalog(catalog, allow_date='2026-11-11').select('scenario:4')
        pid = 10 if role == 'H' else 20
        link = {'session_id': 'shared-lobby', 'game_pid': pid, 'role': role,
                'membership': {'session_id': ('a' if role == 'H' else 'b') * 32, 'revision': pid}}
        original = {'revision': 5, 'attempt_id': 'c' * 32, 'save_digest': 'f' * 64}
        scope = {**link, **original, 'guard_run_id': 'native-' + role}
        request_id = state_digest(scope)[:32]
        check = {**original, 'phase': 'failed', 'reason': 'selection_changed'}
        lobby = {'host_id': 'leon', 'guest_id': 'claire', 'revision': 6, 'connected': True,
                 'ready': {'leon': False, 'claire': False}, 'settings': {}, 'save_slot': 'scenario:4',
                 'save_ref': {'available': False}, 'load_check': check}
        status = {'schema': 1, 'written_at': 100, 'connected': True, 'game_pid': pid, 'role': role,
                  'steam_lobby': 'owned' if role == 'H' else 'joined', 'steam_membership': link['membership'],
                  'lobby': {'version': 1, 'type': 'lobby_state', 'session_id': link['session_id'],
                            'sequence': 8, 'digest': state_digest(lobby), 'data': lobby}}
        guard = {'schema': 1, 'active': True, 'hooks': 26, 'at': 100, 'guard_run_id': scope['guard_run_id'],
                 'prepared_load': {'scope': scope, 'reference': reference}, 'load_request_id': request_id,
                 'policy_id': request_id, 'load_phase': 'scene_loaded', 'load_error': '', 'writes': None,
                 'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4, 'allowed_load_calls': 1,
                 'denied_loads': 0}
        write_json(data / 're2_coop_lobby.json', status)
        write_json(data / 're2_coop_save_guard.json', guard)
        write_json(data / 're2_coop_load_state.json', sample())
        return PreparedCheckpoint(data, pid, role), status, guard

    def test_matches_both_native_checkpoints_after_the_catalog_invalidates_preflight(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            downloaded = transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            self.assertEqual(serve.result(), downloaded)
        self.assertEqual(downloaded, {'scope': SCOPE, 'attempt_id': 'c' * 32, 'checkpoint_match': True})
        payload = b''.join(pair.sent_by_host)
        self.assertNotIn(b'guard_run_id', payload)
        self.assertNotIn(sample()['state']['checkpoint']['save_guid'].encode(), payload)

    def test_guest_checkpoint_mismatch_does_not_acknowledge_host(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        different = sample()
        different['state']['checkpoint']['location'] += 1
        write_json(guest.data / 're2_coop_load_state.json', different)
        pair = NativePipePair()
        with patch.object(transfer, 'TIMEOUT', 1), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaisesRegex(ValueError, 'native checkpoints differ'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            with self.assertRaises(TimeoutError):
                serve.result()

    def test_host_rechecks_its_checkpoint_after_guest_acknowledgment(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        confirm = guest.confirm

        def move_host(snapshot):
            result = confirm(snapshot)
            changed = sample()
            changed['sequence'] += 1
            changed['state']['checkpoint']['location'] += 1
            write_json(host.data / 're2_coop_load_state.json', changed)
            return result

        pair = NativePipePair()
        with patch.object(guest, 'confirm', move_host), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            with self.assertRaisesRegex(ValueError, 'native checkpoints differ'):
                serve.result()

    def test_changed_lobby_attempt_and_manual_load_do_not_attest(self):
        witness, status, guard = self.fixture('G')
        body = status['lobby']['data']
        original = body['load_check'].copy()
        for change in ({'attempt_id': 'd' * 32}, {'reason': 'cancelled'}):
            body['load_check'] = {**original, **change}
            status['lobby']['digest'] = state_digest(body)
            write_json(witness.data / 're2_coop_lobby.json', status)
            with self.subTest(change=change), self.assertRaises(ValueError):
                witness.capture(SESSION)
        body['load_check'] = original
        status['lobby']['digest'] = state_digest(body)
        status['steam_membership']['revision'] += 1
        write_json(witness.data / 're2_coop_lobby.json', status)
        with self.assertRaisesRegex(ValueError, 'different Steam lobby attempt'):
            witness.capture(SESSION)
        status['steam_membership']['revision'] -= 1
        write_json(witness.data / 're2_coop_lobby.json', status)
        guard.pop('prepared_load')
        write_json(witness.data / 're2_coop_save_guard.json', guard)
        with self.assertRaisesRegex(ValueError, 'no native load admitted'):
            witness.capture(SESSION)

    def test_expired_and_unfinished_native_receipts_do_not_attest(self):
        witness, _, guard = self.fixture('H')
        for change in ({'load_phase': 'loading'}, {'at': 96}, {'policy_id': 'e' * 32}, {'writes': {'save': 1}}):
            write_json(witness.data / 're2_coop_save_guard.json', {**guard, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                witness.capture(SESSION)
