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
from tests.test_save_protection import protection_documents, write_protection
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
                 'protection_active': True, 'protection': {'game_pid': pid, 'run_id': 'd' * 32},
                 'prepared_load': {'scope': scope, 'reference': reference}, 'load_request_id': request_id,
                 'policy_id': request_id, 'load_phase': 'scene_loaded', 'load_error': '', 'writes': None,
                 'load_started_at': 98, 'allowed_slot': 4, 'load_index': 4, 'allowed_load_calls': 1,
                 'denied_loads': 0}
        guard['load_hold'] = {'schema': 1, 'scope': 'prepared_load_native_pause', 'observed_at': 100,
                              'phase': 'held', 'native_phase': 'held', 'available': True, 'reason': '',
                              'load_request_id': request_id, 'pause_id': request_id,
                              'guard_run_id': scope['guard_run_id']}
        write_json(data / 're2_coop_lobby.json', status)
        write_json(data / 're2_coop_save_guard.json', guard)
        write_json(data / 're2_coop_load_state.json', sample())
        native, launch = protection_documents()
        write_protection(data, {**native, 'game_pid': pid, 'run_id': 'd' * 32},
                         {**launch, 'game_pid': pid, 'run_id': 'd' * 32})
        return PreparedCheckpoint(data, pid, role), status, guard

    def test_checkpoint_requires_protection_for_its_own_game(self):
        witness, _, guard = self.fixture('H')
        native, launch = protection_documents()
        write_protection(witness.data, native, launch)
        guard['protection'] = {'game_pid': 42, 'run_id': 'a' * 32}
        write_json(witness.data / 're2_coop_save_guard.json', guard)
        with self.assertRaisesRegex(ValueError, 'protected game process'):
            witness.capture(SESSION)

    def test_checkpoint_rejects_protection_lost_during_read(self):
        witness, _, _ = self.fixture('H')
        original = witness.reader.for_load

        def lose_protection(*args):
            evidence = original(*args)
            (witness.data / 're2_coop_protected_launch.json').unlink()
            return evidence

        with (patch.object(witness.reader, 'for_load', side_effect=lose_protection),
              self.assertRaises(OSError)):
            witness.capture(SESSION)

    def test_checkpoint_rejects_a_replaced_protection_binding_during_read(self):
        witness, _, guard = self.fixture('H')
        original = witness.reader.for_load

        def replace_protection(*args):
            evidence = original(*args)
            native, launch = protection_documents()
            write_protection(witness.data, {**native, 'game_pid': 10}, {**launch, 'game_pid': 10})
            guard['protection'] = {'game_pid': 10, 'run_id': 'a' * 32}
            write_json(witness.data / 're2_coop_save_guard.json', guard)
            return evidence

        with (patch.object(witness.reader, 'for_load', side_effect=replace_protection),
              self.assertRaisesRegex(ValueError, 'native load binding changed')):
            witness.capture(SESSION)

    def test_matches_both_native_checkpoints_after_the_catalog_invalidates_preflight(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            downloaded = transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            self.assertEqual(serve.result(), downloaded)
        self.assertEqual(downloaded, {'scope': SCOPE, 'attempt_id': 'c' * 32, 'checkpoint_match': True,
                                      'native_pause_match': True})
        payload = b''.join(pair.sent_by_host)
        self.assertNotIn(b'guard_run_id', payload)
        self.assertNotIn(sample()['state']['checkpoint']['save_guid'].encode(), payload)

    def test_campaign_resume_requires_another_exchange_on_the_same_link(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        attempt = 'c' * 32
        with ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, attempt,
                                resume=lambda: None)
            received = transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, attempt,
                                                            resume=lambda: None)
            self.assertEqual(serve.result(), received)
        self.assertIs(received['resume_authorized'], True)
        self.assertEqual(received['attempt_id'], attempt)

    def test_read_only_guest_does_not_authorize_campaign_resume(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        attempt = 'c' * 32
        pair = NativePipePair()
        with patch.object(transfer, 'TIMEOUT', .5), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, attempt,
                                resume=lambda: None)
            received = transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, attempt)
            self.assertNotIn('resume_authorized', received)
            with self.assertRaises(TimeoutError):
                serve.result()

    def test_campaign_resume_rechecks_the_original_checkpoint_after_the_pair_agrees(self):
        host, _, _ = self.fixture('H')
        guest, _, guard = self.fixture('G')
        pair = NativePipePair()
        attempt = 'c' * 32
        confirm = guest.confirm
        calls = 0

        def verify(snapshot):
            nonlocal calls
            result = confirm(snapshot)
            calls += 1
            if calls == 2:
                guard['load_hold'].update(available=False, native_phase='released')
                write_json(guest.data / 're2_coop_save_guard.json', guard)
            return result

        with (patch.object(transfer, 'TIMEOUT', .5), patch.object(guest, 'confirm', side_effect=verify),
              ThreadPoolExecutor(max_workers=2) as pool):
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, attempt,
                                resume=lambda: None)
            with self.assertRaisesRegex(ValueError, 'owned native pause'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, attempt,
                                                     resume=lambda: None)
            with self.assertRaises(TimeoutError):
                serve.result()

    def test_campaign_guest_waits_for_host_commit_after_its_final_ack(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        attempt = 'c' * 32

        def host_checks():
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ValueError('host lost storage protection')

        checks = 0
        with patch.object(transfer, 'TIMEOUT', .5), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, attempt,
                                resume=host_checks)
            with self.assertRaisesRegex(TimeoutError, 'host did not commit'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, attempt,
                                                     resume=lambda: None)
            with self.assertRaisesRegex(ValueError, 'host lost storage protection'):
                serve.result()

    def test_same_checkpoint_is_rejected_without_a_fresh_matching_owned_pause(self):
        witness, _, guard = self.fixture('H')
        original = guard['load_hold'].copy()
        changes = ({'available': False}, {'phase': 'requesting'}, {'native_phase': 'released'},
                   {'pause_id': '0' * 32}, {'load_request_id': '0' * 32}, {'guard_run_id': 'old-vm'},
                   {'observed_at': 96}, {'observed_at': 101}, {'schema': True}, {'reason': 'pause_ended_externally'})
        for change in changes:
            guard['load_hold'] = {**original, **change}
            write_json(witness.data / 're2_coop_save_guard.json', guard)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'owned native pause'):
                witness.capture(SESSION)
        guard.pop('load_hold')
        write_json(witness.data / 're2_coop_save_guard.json', guard)
        with self.assertRaisesRegex(ValueError, 'owned native pause'):
            witness.capture(SESSION)

    def test_remote_pause_claim_requires_the_boolean_true(self):
        witness, _, _ = self.fixture('H')
        snapshot = witness.capture(SESSION)
        for value in (1, 0, 'true', None, False):
            snapshot['state']['flags'][SCOPE]['native_pause_held'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'different Steam lobby attempt'):
                witness.confirm(snapshot)

    def test_pause_loss_during_checkpoint_read_is_not_reported_as_a_match(self):
        witness, _, guard = self.fixture('H')
        original = witness.reader.for_load

        def unpause_during_read(*args):
            evidence = original(*args)
            guard['load_hold'].update(available=False, native_phase='released')
            write_json(witness.data / 're2_coop_save_guard.json', guard)
            return evidence

        with patch.object(witness.reader, 'for_load', side_effect=unpause_during_read):
            with self.assertRaisesRegex(ValueError, 'owned native pause'):
                witness.capture(SESSION)

    def test_guest_losing_pause_after_first_ack_never_finishes_confirmation(self):
        host, _, _ = self.fixture('H')
        guest, _, guard = self.fixture('G')
        original = guest.confirm
        calls = 0

        def resume_after_first_ack(snapshot):
            nonlocal calls
            result = original(snapshot)
            calls += 1
            if calls == 1:
                guard['load_hold'].update(available=False, native_phase='released')
                write_json(guest.data / 're2_coop_save_guard.json', guard)
            return result

        pair = NativePipePair()
        with (patch.object(transfer, 'TIMEOUT', .5), patch.object(guest, 'confirm', side_effect=resume_after_first_ack),
              ThreadPoolExecutor(max_workers=2) as pool):
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaisesRegex(ValueError, 'owned native pause'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            with self.assertRaises(TimeoutError):
                serve.result()

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
        with (patch.object(guest, 'confirm', move_host), patch.object(transfer, 'TIMEOUT', 1),
              ThreadPoolExecutor(max_workers=2) as pool):
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaisesRegex(TimeoutError, 'final checkpoint confirmation'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            with self.assertRaisesRegex(ValueError, 'native checkpoints differ'):
                serve.result()

    def test_guest_rechecks_its_checkpoint_before_acknowledging_the_host_confirmation(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        confirm = host.confirm

        def move_guest(snapshot):
            result = confirm(snapshot)
            changed = sample()
            changed['sequence'] += 1
            changed['state']['checkpoint']['location'] += 1
            write_json(guest.data / 're2_coop_load_state.json', changed)
            return result

        pair = NativePipePair()
        with (patch.object(host, 'confirm', move_guest), patch.object(transfer, 'TIMEOUT', 1),
              ThreadPoolExecutor(max_workers=2) as pool):
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaisesRegex(ValueError, 'native checkpoints differ'):
                transfer.confirm_prepared_checkpoint(pair.pipe(b'G'), b'G', guest, SESSION, REQUEST)
            with self.assertRaisesRegex(TimeoutError, 'final checkpoint confirmation'):
                serve.result()

    def test_old_checkpoint_client_cannot_acknowledge_the_new_exchange(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        with patch.object(transfer, 'TIMEOUT', 0.5), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaises(TimeoutError):
                transfer.transfer(pair.pipe(b'G'), b'G', SESSION, REQUEST, verify=guest.confirm)
            with self.assertRaises(TimeoutError):
                serve.result()
        self.assertEqual(pair.sent_by_host, [])

    def test_guest_rejects_a_new_native_epoch_between_the_two_transfers(self):
        host, _, _ = self.fixture('H')
        guest, _, _ = self.fixture('G')
        pair = NativePipePair()
        guest_pipe = pair.pipe(b'G')
        request = guest_pipe.request
        acknowledged = False

        def change_epoch_after_acknowledgment(command):
            nonlocal acknowledged
            if command == b'R' and acknowledged:
                return b'Gepoch-02'
            reply = request(command)
            if command.startswith(b'S') and command[-4:] == b'\xff' * 4 and reply == b'S':
                acknowledged = True
            return reply

        guest_pipe.request = change_epoch_after_acknowledgment
        with patch.object(transfer, 'TIMEOUT', 1), ThreadPoolExecutor(max_workers=2) as pool:
            serve = pool.submit(transfer.confirm_prepared_checkpoint, pair.pipe(b'H'), b'H', host, SESSION, REQUEST)
            with self.assertRaisesRegex(OSError, 'peer changed'):
                transfer.confirm_prepared_checkpoint(guest_pipe, b'G', guest, SESSION, REQUEST)
            with self.assertRaises(TimeoutError):
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
