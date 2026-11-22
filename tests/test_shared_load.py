from copy import deepcopy
import hashlib
import json
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import unittest
from unittest.mock import patch

from load_preflight import NativeSaveSource
from lobby_control import submit
from lobby_sync import LobbyGuest, LobbyHost, write_json
from protocol.v1 import ProtocolError, decode, encode
from readonly_save_control import arm
from save_catalog import SaveCatalog, reference_identity_digest
from steam_pose_bridge import PoseHost, _encode, envelope, run_bridge
from tests.test_save_catalog import source
from tests.test_save_protection import protection_documents, write_protection


class SharedLoadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data, self.saves = self.directory / 'data', self.directory / 'saves'
        self.data.mkdir(); self.saves.mkdir()
        self.clock = patch('save_catalog.time.time', return_value=100).start()
        self.ticks = patch('lobby_sync.time.monotonic', return_value=50).start()
        self.addCleanup(patch.stopall)
        self.catalog_path = self.data / 're2_coop_save_catalog.json'
        write_json(self.catalog_path, source())
        self.file = self.saves / 'data004Slot.bin'
        self.payload = b'synthetic encrypted save fixture; not a real RE2 save'
        self.file.write_bytes(self.payload)
        self.local = NativeSaveSource(self.data, self.saves, allow_date='2026-11-11')
        self.reference = self.local.catalog.select('scenario:4')

    def lobby(self):
        host = LobbyHost('session', 'host', 'guest', save_slot='scenario:4',
                         catalog=SaveCatalog(self.catalog_path, allow_date='2026-11-11'), load_source=self.local)
        host.connect()
        host.snapshot()
        for player in ('host', 'guest'):
            host.set_ready(player, True, host.lobby.revision, save_identity=reference_identity_digest(host.save_ref))
        guest = LobbyGuest('host', 'guest', catalog=self.local.catalog)
        return host, guest

    def prepare(self):
        host, guest = self.lobby()
        host.check_load(host.lobby.revision)
        self.assertTrue(guest.receive(host.snapshot(), 'session'))
        ack = guest.load_ack(self.local)
        self.assertTrue(host.acknowledge_load(ack))
        self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'prepared')
        return host, guest, ack

    def test_new_steam_membership_discards_old_pose_readiness_and_load_ack(self):
        host = PoseHost('host', 'guest', lobby_config={
            'save_slot': 'scenario:4', 'catalog': self.local.catalog, 'load_source': self.local,
        })
        self.assertFalse(host.bind_membership(1))
        original = host.state.session_id
        host.receive(envelope('hello', request_id='1' * 32), now=100)
        host.lobby.snapshot()
        for player in ('host', 'guest'):
            host.lobby.set_ready(player, True, host.lobby.lobby.revision,
                                 save_identity=reference_identity_digest(self.reference))
        host.lobby.check_load(host.lobby.lobby.revision)
        guest = LobbyGuest('host', 'guest', catalog=self.local.catalog)
        self.assertTrue(guest.receive(host.lobby.snapshot(), original))
        ack = guest.load_ack(self.local)
        host.receive(ack, now=100)
        pose = {**envelope('propose', session_id=original), 'kind': 'player', 'target': 'guest', 'value': {
            'position': [1, 2, 3], 'rotation': [0, 0, 0, 1], 'observer_run_id': 'guest-run',
            'observer_sequence': 1, 'observed_at': 100, 'tdb': 70,
        }}
        self.assertIsNotNone(host.receive(pose, now=100))
        self.assertEqual(host.lobby.snapshot()['data']['load_check']['phase'], 'prepared')
        self.assertFalse(host.bind_membership(1))
        self.assertEqual(host.state.session_id, original)

        self.assertTrue(host.bind_membership(2))
        first_snapshot = host.receive(envelope('hello', request_id='2' * 32), now=100)
        self.assertNotEqual(first_snapshot['data']['session_id'], original)
        self.assertEqual(first_snapshot['data']['state']['players'], {})
        lobby = host.lobby.snapshot()
        self.assertEqual(lobby['data']['save_slot'], 'scenario:4')
        self.assertFalse(any(lobby['data']['ready'].values()))
        self.assertIsNone(lobby['data']['load_check'])
        host.receive(envelope('lobby_ready', session_id=original, revision=lobby['data']['revision'],
                              value=True, save_identity=reference_identity_digest(self.reference)), now=100)
        self.assertFalse(any(host.lobby.snapshot()['data']['ready'].values()))
        with patch.object(host.lobby, 'acknowledge_load') as acknowledge:
            host.receive(ack, now=100)
            acknowledge.assert_not_called()
        pose['value']['observer_sequence'] = 2
        self.assertIsNone(host.receive(pose, now=100))

    def test_fingerprint_uses_file_bytes_and_keeps_every_file_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.saves.iterdir()}
        self.assertEqual(self.local.fingerprint(self.reference), hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.saves.iterdir()})
        newer = deepcopy(self.reference); newer['slot_id'] = 0
        with self.assertRaises(ValueError):
            self.local.fingerprint(newer)
        wrong = deepcopy(self.reference); wrong['scenario'] = 0
        with self.assertRaises(ValueError):
            self.local.fingerprint(wrong)
        self.clock.return_value = 104
        with self.assertRaises(ValueError):
            self.local.fingerprint(self.reference)

    def test_missing_empty_oversized_or_linked_file_is_rejected(self):
        self.file.unlink()
        with self.assertRaises(OSError):
            self.local.fingerprint(self.reference)
        self.file.write_bytes(b'')
        with self.assertRaises(ValueError):
            self.local.fingerprint(self.reference)
        self.file.write_bytes(self.payload)
        with patch('load_preflight.MAX_SAVE_BYTES', 3), self.assertRaises(ValueError):
            self.local.fingerprint(self.reference)
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
            self.local.fingerprint(self.reference)
        with self.assertRaises(ValueError):
            NativeSaveSource(self.data, Path('relative'), allow_date='2026-11-11')
        with self.assertRaises(ValueError):
            NativeSaveSource(self.data, self.saves, allow_date=None)

    def test_file_replacement_or_mutation_during_hash_never_produces_a_digest(self):
        real_hash = hashlib.sha256
        case = self
        class MutatingHash:
            def __init__(self):
                self.inner = real_hash()
            def update(self, chunk):
                self.inner.update(chunk)
                case.file.write_bytes(case.payload + b'changed')
            def hexdigest(self):
                return self.inner.hexdigest()
        with patch('load_preflight.sha256', MutatingHash), self.assertRaises(ValueError):
            self.local.fingerprint(self.reference)

    def test_both_ready_native_selection_is_required(self):
        host, _ = self.lobby()
        host.set_ready('guest', False, host.lobby.revision)
        with self.assertRaises(ValueError):
            host.check_load(host.lobby.revision)
        host.set_ready('guest', True, host.lobby.revision, save_identity=reference_identity_digest(host.save_ref))
        with self.assertRaises(ValueError):
            host.check_load(host.lobby.revision - 1)
        host.check_load(host.lobby.revision)
        self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'checking')

    def test_campaign_requires_fresh_guest_consent_for_the_selected_save(self):
        host, guest = self.lobby()
        revision = host.lobby.revision
        with self.assertRaisesRegex(ValueError, 'guest campaign consent'):
            host.check_load(revision, start_campaign=True)
        guest.receive(host.snapshot(), 'session')
        consent = guest.ready_message(True, campaign_consent=True)
        self.assertEqual(decode(encode(consent, steam_pose=True), steam_pose=True), consent)
        host.set_ready('guest', True, revision, save_identity=consent['save_identity'],
                       campaign_consent=consent['campaign_consent'])
        host.check_load(revision, start_campaign=True)
        self.assertIs(host.snapshot()['data']['load_check']['campaign_start'], True)
        host.set_ready('guest', False, revision)
        self.assertFalse(host.campaign_ready())
        with self.assertRaises(ValueError):
            host.check_load(revision, start_campaign=True)

    def test_matching_files_prepare_only_and_do_not_start_the_lobby(self):
        host, guest, ack = self.prepare()
        self.assertFalse(host.lobby.started)
        self.assertEqual(decode(encode(ack, steam_pose=True), steam_pose=True), ack)
        with self.assertRaises(ProtocolError):
            encode(ack)
        self.assertTrue(guest.receive(host.snapshot(), 'session'))
        self.assertEqual(self.file.read_bytes(), self.payload)

    def test_duplicate_or_older_ack_does_not_renew_the_receiver_clock_lease(self):
        host, _, ack = self.prepare()
        self.ticks.return_value = 54
        self.assertFalse(host.acknowledge_load(ack))
        self.ticks.return_value = 55
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'guest_ack_expired')
        late = {**ack, 'sequence': ack['sequence'] + 1}
        self.assertFalse(host.acknowledge_load(late), 'a failed attempt was revived by a late acknowledgment')

    def test_only_new_ack_renews_prepared_and_absent_guest_expires(self):
        host, guest, _ = self.prepare()
        self.ticks.return_value = 54
        self.assertTrue(guest.receive(host.snapshot(), 'session'))
        self.assertTrue(host.acknowledge_load(guest.load_ack(self.local)))
        self.ticks.return_value = 58
        self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'prepared')
        self.ticks.return_value = 59
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'guest_ack_expired')
        self.ticks.return_value = 60
        host.check_load(host.lobby.revision)
        self.ticks.return_value = 65
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'guest_ack_expired')

    def test_old_guest_lobby_cannot_renew_preparation_or_ready_again(self):
        host, guest, _ = self.prepare()
        current = host.snapshot()
        self.assertTrue(guest.receive(current, 'session'))
        self.ticks.return_value = 52
        self.assertFalse(guest.receive(current, 'past-session'))
        self.ticks.return_value = 53
        with patch.object(self.local, 'fingerprint') as fingerprint:
            self.assertIsNone(guest.load_ack(self.local))
        fingerprint.assert_not_called()
        with self.assertRaises(ValueError):
            guest.ready_message(True)
        self.assertFalse(guest.ready_message(False)['value'])
        self.assertTrue(guest.receive(current, 'session'))
        self.assertTrue(guest.ready_message(True)['value'])

    def test_hash_finishing_after_guest_lobby_expires_cannot_renew_attempt(self):
        _, guest, _ = self.prepare()

        def slow_fingerprint(_reference):
            self.ticks.return_value = 53
            return hashlib.sha256(self.payload).hexdigest()

        with patch.object(self.local, 'fingerprint', side_effect=slow_fingerprint) as fingerprint:
            self.assertIsNone(guest.load_ack(self.local))
        fingerprint.assert_called_once()

    def test_slow_host_fingerprint_cannot_publish_or_renew_expired_preparation(self):
        for action in ('publish', 'acknowledge'):
            with self.subTest(action=action):
                self.ticks.return_value = 50
                host, _, ack = self.prepare()
                self.ticks.return_value = 54

                def slow_fingerprint(reference):
                    self.assertEqual(reference, self.reference)
                    self.ticks.return_value = 55
                    return ack['save_digest']

                with patch.object(self.local, 'fingerprint', side_effect=slow_fingerprint) as fingerprint:
                    if action == 'acknowledge':
                        self.assertFalse(host.acknowledge_load({**ack, 'sequence': ack['sequence'] + 1}))
                    check = host.snapshot()['data']['load_check']
                fingerprint.assert_called_once()
                self.assertEqual((check['phase'], check['reason']), ('failed', 'guest_ack_expired'))

    def test_failed_new_local_comparison_revokes_previous_prepared_immediately(self):
        host, _, _ = self.prepare()
        self.file.unlink()
        with self.assertRaises(OSError):
            host.check_load(host.lobby.revision)
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'local_source_unavailable')

    def test_start_needs_both_staged_commands_and_survives_native_catalog_busy(self):
        host, guest, _ = self.prepare()
        host_stage, guest_stage = 'a' * 32, 'b' * 32
        self.assertFalse(host.begin_start(host_stage))
        guest.receive(host.snapshot(), 'session')
        ack = guest.load_ack(self.local, stage_id=guest_stage)
        self.assertEqual(decode(encode(ack, steam_pose=True), steam_pose=True), ack)
        self.assertTrue(host.acknowledge_load(ack))
        self.assertFalse(host.begin_start(None))
        self.assertTrue(host.begin_start(host_stage))
        before = host.snapshot()
        self.assertEqual(before['data']['load_check']['start'],
                         {'H': host_stage, 'G': guest_stage, 'guest_ack_sequence': ack['sequence']})
        self.assertEqual(before['data']['load_check']['phase'], 'starting')
        current_catalog = host.catalog.snapshot()
        with patch.object(host.catalog, 'snapshot', side_effect=[current_catalog, {
            'available': False, 'reason': 'save_service_busy', 'entries': [],
        }]) as snapshot:
            self.assertEqual(host.snapshot(), before)
        snapshot.assert_called_once()
        write_json(self.catalog_path, {**source(2), 'available': False, 'reason': 'save_service_busy', 'entries': []})
        self.ticks.return_value = 51
        self.assertEqual(host.snapshot(), before)
        self.assertTrue(guest.receive(before, 'session'))
        self.assertIsNone(guest.load_ack(self.local, stage_id=guest_stage))
        self.assertFalse(host.acknowledge_load({**ack, 'sequence': ack['sequence'] + 1}))
        self.ticks.return_value = 55
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'start_window_expired')
        self.assertFalse(host.begin_start(host_stage))

    def test_delayed_start_and_local_withdrawal_cannot_authorize_the_guest(self):
        for cause in ('delay', 'withdrawal'):
            with self.subTest(cause=cause):
                self.ticks.return_value = 50
                host, guest, _ = self.prepare()
                guest.receive(host.snapshot(), 'session')
                stage = 'b' * 32
                ack = guest.load_ack(self.local, stage_id=stage)
                self.ticks.return_value = 52
                self.assertTrue(host.acknowledge_load(ack))
                self.assertTrue(host.begin_start('a' * 32))
                decision = host.snapshot()
                self.assertTrue(guest.receive(decision, 'session'))
                self.assertIsNotNone(guest.start_deadline(guest.current_message(), stage))
                if cause == 'delay':
                    self.ticks.return_value = 55
                    self.assertTrue(guest.receive(decision, 'session'))
                else:
                    guest.ready_message(False)
                self.assertIsNone(guest.start_deadline(guest.current_message(), stage))

    def test_start_grant_is_revoked_by_cancel_disconnect_or_revision_change(self):
        for revocation in ('cancel', 'disconnect', 'change'):
            with self.subTest(revocation=revocation):
                host, guest, _ = self.prepare()
                guest.receive(host.snapshot(), 'session')
                self.assertTrue(host.acknowledge_load(guest.load_ack(self.local, stage_id='b' * 32)))
                self.assertTrue(host.begin_start('a' * 32))
                if revocation == 'cancel':
                    host.cancel_load_check()
                elif revocation == 'disconnect':
                    host.disconnect()
                else:
                    host.configure('scenario:4', {'friendly_fire': False}, host.lobby.revision)
                check = host.snapshot()['data']['load_check']
                self.assertEqual(check['phase'], 'failed')
                self.assertNotIn('start', check)

    def test_foreign_session_revision_attempt_and_out_of_order_acks_cannot_prepare(self):
        host, guest = self.lobby()
        host.check_load(host.lobby.revision)
        guest.receive(host.snapshot(), 'session')
        ack = guest.load_ack(self.local)
        for key, value in (('session_id', 'old'), ('revision', ack['revision'] - 1), ('attempt_id', '0' * 32)):
            self.assertFalse(host.acknowledge_load({**ack, key: value}))
        self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'checking')
        self.assertTrue(host.acknowledge_load({**ack, 'sequence': 2}))
        self.assertFalse(host.acknowledge_load(ack))

    def test_mismatched_and_unavailable_guest_files_fail_the_attempt(self):
        for change, expected in (({'save_digest': 'f' * 64}, 'guest_file_mismatch'),
                                 ({'save_digest': None, 'accepted': False}, 'guest_source_unavailable')):
            host, guest = self.lobby()
            host.check_load(host.lobby.revision)
            guest.receive(host.snapshot(), 'session')
            self.assertTrue(host.acknowledge_load({**guest.load_ack(self.local), **change}))
            self.assertEqual(host.snapshot()['data']['load_check']['reason'], expected)

    def test_new_attempt_and_rejoin_reject_old_prepared_messages(self):
        host, _, old = self.prepare()
        host.check_load(host.lobby.revision)
        self.assertFalse(host.acknowledge_load(old))
        self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'checking')
        host.disconnect(); host.connect()
        self.assertFalse(host.acknowledge_load(old))
        self.assertFalse(any(host.snapshot()['data']['ready'].values()))
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'selection_changed')

    def test_host_file_metadata_readiness_or_connection_change_invalidates_prepared(self):
        for change in ('file', 'missing', 'metadata', 'settings', 'unready', 'disconnect', 'cancel'):
            with self.subTest(change=change):
                self.file.write_bytes(self.payload)
                write_json(self.catalog_path, source())
                self.ticks.return_value = 50
                host, _, _ = self.prepare()
                if change == 'file': self.file.write_bytes(b'other file bytes')
                elif change == 'missing': self.file.unlink()
                elif change == 'metadata':
                    value = source(2); value['entries'][1]['timestamp'] = str(int(self.reference['timestamp']) + 10_000_000)
                    write_json(self.catalog_path, value)
                elif change == 'unready': host.set_ready('host', False, host.lobby.revision)
                elif change == 'settings': host.configure('scenario:4', {'friendly_fire': False}, host.lobby.revision)
                elif change == 'disconnect': host.disconnect()
                else: host.cancel_load_check()
                self.ticks.return_value = 51
                self.assertEqual(host.snapshot()['data']['load_check']['phase'], 'failed')

    def test_cancel_revokes_the_attempt_after_native_selection_loss(self):
        host, _, ack = self.prepare()
        host.set_ready('guest', False, host.lobby.revision)
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'selection_changed')
        host.cancel_load_check()
        self.assertEqual(host.snapshot()['data']['load_check']['reason'], 'cancelled')
        self.assertFalse(host.acknowledge_load({**ack, 'sequence': ack['sequence'] + 1}))

    def test_malformed_load_state_or_ack_is_a_protocol_error(self):
        host, guest, ack = self.prepare()
        state = host.snapshot()
        for key, value in (('reason', []), ('phase', {}), ('revision', True), ('save_digest', None)):
            malformed = deepcopy(state)
            malformed['data']['load_check'][key] = value
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                encode(malformed, steam_pose=True)
        for key, value in (('accepted', 1), ('sequence', True), ('attempt_id', []), ('save_digest', 'x')):
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                encode({**ack, key: value}, steam_pose=True)
        guest.message = None
        self.assertIsNone(guest.load_ack(self.local))


class SharedLoadBridgeTests(unittest.TestCase):
    def test_two_bridge_loops_compare_files_and_revoke_on_guest_change(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = [root / 'host', root / 'guest']
            saves = [root / 'host-saves', root / 'guest-saves']
            for directory in data + saves:
                directory.mkdir()
            for directory in data:
                write_json(directory / 're2_coop_save_catalog.json', source(stamp=int(time())))
            matching_bytes = b'same synthetic encrypted fixture'
            for directory in saves:
                (directory / 'data004Slot.bin').write_bytes(matching_bytes)
            inboxes, errors, stops = [Queue(), Queue()], Queue(), [Event(), Event()]
            pause_lobby, pong_seen, scoped_campaigns = Event(), Event(), Event()
            class Link:
                lobby_name = 'fixture-lobby'

                def __init__(self, index):
                    self.index, self.role, self.epoch = index, (b'H', b'G')[index], b'load-test'
                    self.game_pid = index + 100
                def lobby_status(self): return ('owned', 'joined')[self.index]
                def membership_revision(self): return 1
                def save_directory(self): return saves[self.index]
                def cloud_status(self): return 'cloud-app-disabled'
                def request(self, *args, **kwargs): return b'peer-ready'
                def receive(self):
                    try: return inboxes[self.index].get_nowait()
                    except Empty: return None
                def send(self, message):
                    if message['type'] == 'campaign_pose_capability' and not scoped_campaigns.is_set():
                        return
                    if self.index == 0 and message['type'] == 'lobby_state' and (
                            message['data'].get('load_check') or {}).get('phase') == 'failed':
                        report = json.loads((data[0] / 're2_coop_lobby.json').read_text(encoding='utf-8'))
                        self_test.assertNotIn('prepared_start', report)
                    if self.index == 0 and pause_lobby.is_set():
                        if message['type'] == 'lobby_state':
                            return
                        if message['type'] == 'pong':
                            pong_seen.set()
                    inboxes[1 - self.index].put(_encode(message))
            self_test = self
            links = [Link(0), Link(1)]
            campaign_requests = Queue()

            def stage_campaign(index, slot):
                self.assertEqual(slot, 'scenario:4')
                request = stage(index)
                campaign_requests.put((index, request))
                return request

            def run(index):
                try:
                    run_bridge(data[index], links[index], (b'H', b'G')[index], 'host', 'guest',
                               stop=stops[index], lobby_enabled=True,
                               lobby_config={'save_slot': 'scenario:4'} if index == 0 else None,
                               save_catalog=SaveCatalog(data[0] / 're2_coop_save_catalog.json', allow_date='2026-11-11') if index == 0 else None,
                               load_source=NativeSaveSource(data[index], saves[index], allow_date='2026-11-11'),
                               stage_campaign=lambda slot: stage_campaign(index, slot))
                except BaseException as exc: errors.put(exc)
            def wait_status(index, predicate):
                deadline = monotonic() + 4
                status = None
                while monotonic() < deadline:
                    if not errors.empty(): raise errors.get()
                    try:
                        status = json.loads((data[index] / 're2_coop_lobby.json').read_text(encoding='utf-8'))
                        if predicate(status):
                            return status
                    except (OSError, ValueError): pass
                    sleep(0.01)
                self.fail(f'shared load state did not reach the bridge: {status}')

            def wait(index, predicate):
                return wait_status(index, lambda status: status['connected'] and status['lobby']
                                   and predicate(status['lobby']['data']))

            def stage(index):
                directory, pid = data[index], links[index].game_pid
                stamp = int(time())
                native, launched = protection_documents(stamp)
                write_protection(directory, {**native, 'game_pid': pid}, {**launched, 'game_pid': pid})
                guard = {'schema': 1, 'active': True, 'hooks': 26, 'at': stamp, 'protection_active': True,
                         'protection': {'game_pid': pid, 'run_id': 'a' * 32}, 'guard_run_id': f'run-{index}',
                         'denied_loads': 0, 'command_id': '', 'load_request_id': '', 'command_error': ''}
                path = directory / 're2_coop_save_guard.json'
                write_json(path, guard)
                # Exercise the real protected CLI with a simulated local Steam plugin.
                request = arm(directory, 'scenario:4', '2026-11-11', load=True, prepared_lobby=saves[index])
                policy = json.loads((directory / 're2_coop_save_policy.json').read_text())
                write_json(path, {**guard, 'staged_load': {'id': request, 'requested_at': policy['at']}})
                return request

            with (patch('steam_pose_bridge.CHECK_INTERVAL', 0.1), patch('steam_pose_bridge.LOBBY_INTERVAL', 0.1),
                  patch('steam_pose_bridge.RETRY_INTERVAL', 0.1), patch('lobby_sync.GUEST_LOBBY_LEASE', 1.5),
                  patch('readonly_save_control.SteamPipe', side_effect=lambda pid: links[pid - 100]),
                  patch('readonly_save_control._storage_guard_active', return_value=True),
                  patch('steam_pose_bridge.storage_guard_active', return_value=True)):
                threads = [Thread(target=run, args=(i,)) for i in (0, 1)]
                for thread in threads: thread.start()
                try:
                    wait(0, lambda d: d.get('save_ref', {}).get('slot_id') == 4)
                    wait(1, lambda d: d.get('save_ref', {}).get('slot_id') == 4)
                    with self.assertRaises(ValueError): submit(data[1], 'check-load', True)
                    submit(data[0], 'ready', True); submit(data[1], 'ready', True)
                    ordinary = wait(0, lambda d: all(d['ready'].values()))
                    self.assertFalse(ordinary['campaign_peer_supported'])
                    self.assertFalse(ordinary['campaign_start_ready'])
                    submit(data[0], 'start-campaign', True)
                    wait_status(0, lambda s: s['error'] == 'command is not allowed for this role')
                    self.assertTrue(campaign_requests.empty())
                    scoped_campaigns.set()
                    for index in (0, 1):
                        wait_status(index, lambda s: s.get('campaign_peer_supported') is True)
                    submit(data[0], 'check-load', True)
                    wait(1, lambda d: (d.get('load_check') or {}).get('phase') == 'prepared')
                    (saves[1] / 'data004Slot.bin').write_bytes(b'different same-metadata file')
                    failed = wait(1, lambda d: (d.get('load_check') or {}).get('phase') == 'failed')
                    self.assertEqual(failed['lobby']['data']['load_check']['reason'], 'guest_file_mismatch')
                    (saves[1] / 'data004Slot.bin').write_bytes(matching_bytes)
                    write_json(data[0] / 're2_coop_save_catalog.json', source(sequence=2, stamp=int(time())))
                    submit(data[0], 'check-load', True)
                    prepared = wait(1, lambda d: (d.get('load_check') or {}).get('phase') == 'prepared')['lobby']

                    pause_lobby.set()
                    wait_status(1, lambda status: not status['connected'] and status['lobby'] is None)
                    pong_seen.clear()
                    self.assertTrue(pong_seen.wait(1), 'Steam pose heartbeat should continue without lobby updates')
                    expired = wait(0, lambda d: not d['ready']['guest']
                                   and (d.get('load_check') or {}).get('phase') == 'failed')
                    self.assertEqual(expired['lobby']['data']['load_check']['reason'], 'selection_changed')
                    write_json(data[1] / 're2_coop_lobby_command.json', {
                        'id': 'expired-ready', 'session_id': prepared['session_id'],
                        'revision': prepared['data']['revision'], 'written_at': int(time()),
                        'action': 'ready', 'value': True})
                    wait_status(1, lambda status: status['error'] == 'guest lobby state expired')

                    pause_lobby.clear()
                    wait(1, lambda d: not d['ready']['guest'])
                    for directory, sequence in zip(data, (3, 2)):
                        write_json(directory / 're2_coop_save_catalog.json', source(sequence=sequence, stamp=int(time())))
                    submit(data[1], 'ready', True)
                    wait(0, lambda d: all(d['ready'].values()))
                    submit(data[0], 'check-load', True)
                    wait(1, lambda d: (d.get('load_check') or {}).get('phase') == 'prepared')
                    guest_catalog = source(sequence=3, stamp=int(time()))
                    guest_catalog['entries'].pop()
                    write_json(data[1] / 're2_coop_save_catalog.json', guest_catalog)
                    withdrawn = wait(0, lambda d: not d['ready']['guest']
                                     and (d.get('load_check') or {}).get('phase') == 'failed')
                    self.assertIn(withdrawn['lobby']['data']['load_check']['reason'],
                                  {'selection_changed', 'guest_source_unavailable'})
                    self.assertFalse((data[0] / 're2_coop_save_policy.json').exists())
                    self.assertFalse((data[1] / 're2_coop_save_policy.json').exists())

                    for first, sequence in ((0, 4), (1, 7)):
                        with self.subTest(first_loader=first):
                            for directory in data:
                                write_json(directory / 're2_coop_save_catalog.json', source(sequence, stamp=int(time())))
                            latest = wait(0, lambda d: d.get('save_ref', {}).get('slot_id') == 4)
                            revision = latest['lobby']['data']['revision']
                            wait_status(1, lambda s: (s.get('lobby') or {}).get('data', {}).get('revision') == revision)
                            for index in (0, 1):
                                submit(data[index], 'ready', True)
                            wait(0, lambda d: all(d['ready'].values()))
                            submit(data[0], 'check-load', True)
                            for index in (0, 1):
                                wait(index, lambda d: (d.get('load_check') or {}).get('phase') == 'prepared')
                            first_id = stage(first)
                            other = 1 - first
                            seen = wait_status(first, lambda s: (s.get('lobby') or {}).get('data', {}).get(
                                'load_check', {}).get('phase') == 'prepared')
                            self.assertNotIn('prepared_start', seen)
                            other_id = stage(other)
                            status = wait_status(first, lambda s: s.get('prepared_start', {}).get('id') == first_id)
                            self.assertEqual(status['lobby']['data']['load_check']['phase'], 'starting')
                            wait_status(other, lambda s: s.get('prepared_start', {}).get('id') == other_id)
                            busy = {**source(sequence + 1, stamp=int(time())), 'available': False,
                                    'reason': 'save_service_busy', 'entries': []}
                            write_json(data[first] / 're2_coop_save_catalog.json', busy)
                            # The first loader consumed its own local receipt and made its catalog busy.
                            (data[first] / 're2_coop_save_guard.json').unlink()
                            wait_status(first, lambda s: 'prepared_start' not in s)
                            status = wait_status(other, lambda s: s.get('prepared_start', {}).get('id') == other_id)
                            self.assertEqual(status['lobby']['data']['load_check']['phase'], 'starting')
                            action, value, reason = (('ready', False, 'selection_changed') if first == 0
                                                     else ('cancel-load-check', True, 'cancelled'))
                            submit(data[0], action, value)
                            for index in (0, 1):
                                wait_status(index, lambda s: 'prepared_start' not in s and (
                                    (s.get('lobby') or {}).get('data', {}).get('load_check') or {}).get('reason') == reason)
                    self.assertTrue(campaign_requests.empty(), 'file-only checks must not stage a campaign')
                    wait(0, lambda d: d['ready']['guest'] is False)
                    for directory in data:
                        write_json(directory / 're2_coop_save_catalog.json', source(sequence=10, stamp=int(time())))
                    revision = wait(0, lambda d: d.get('save_ref', {}).get('slot_id') == 4)['lobby']['data']['revision']
                    wait_status(1, lambda s: s.get('local_save_matches') is True and
                                (s.get('lobby') or {}).get('data', {}).get('revision') == revision)
                    for index in (0, 1):
                        submit(data[index], 'ready', True)
                    ordinary = wait(0, lambda d: all(d['ready'].values()))
                    self.assertFalse(ordinary.get('campaign_start_ready'))
                    submit(data[0], 'start-campaign', True)
                    wait_status(0, lambda s: 'guest campaign consent' in (s.get('error') or ''))
                    self.assertTrue(campaign_requests.empty())
                    submit(data[1], 'ready-campaign', True)
                    wait_status(0, lambda s: s.get('campaign_start_ready') is True)
                    submit(data[0], 'start-campaign', True)
                    for index in (0, 1):
                        status = wait_status(index, lambda s: s.get('prepared_start') is not None)
                        self.assertIs(status['lobby']['data']['load_check']['campaign_start'], True)
                    staged = dict(campaign_requests.get(timeout=1) for _ in (0, 1))
                    self.assertEqual(set(staged), {0, 1})
                    expect = {}
                    for index in (0, 1):
                        request = json.loads((data[index] / 're2_coop_save_policy.json').read_text())
                        expect[index] = request['id']
                        self.assertFalse((data[index] / 're2_coop_lobby_view.json').exists(), 'queue must not hide the menu')
                    self.assertEqual(staged, expect)
                    self.assertTrue(campaign_requests.empty(), 'a repeated lobby message staged the load twice')
                    accepted = data[0] / 're2_coop_save_guard.json'
                    report = json.loads(accepted.read_text())
                    write_json(accepted, {**report, 'command_id': staged[0], 'load_request_id': staged[0],
                                          'load_phase': 'reading_save'})
                    wait_status(0, lambda s: (data[0] / 're2_coop_lobby_view.json').exists())
                    fault = data[1] / 're2_coop_save_guard.json'
                    report = json.loads(fault.read_text())
                    write_json(fault, {**report, 'command_id': staged[1], 'command_error': 'title_not_ready'})
                    wait_status(1, lambda s: s.get('error') == 'Kampagnenstart: title_not_ready')
                    self.assertFalse((data[1] / 're2_coop_lobby_view.json').exists())
                    wait(0, lambda d: not d['ready']['guest'])
                finally:
                    for stop in stops: stop.set()
                    for thread in threads:
                        thread.join(4)
                        self.assertFalse(thread.is_alive())
                    if not errors.empty(): raise errors.get()
