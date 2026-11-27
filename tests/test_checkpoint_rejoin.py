import json
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import unittest
from unittest.mock import Mock, patch
from coop_checkpoint import FILES, HostArchive
from lobby_control import submit
from lobby_sync import LobbyHost, LobbyGuest, write_json
from protocol.v1 import encode, decode
from save_catalog import SaveCatalog
from steam_pose_bridge import run_bridge
from tests.test_new_game_bridges import Peer


class CheckpointRejoinTests(unittest.TestCase):
    def test_fresh_preparation_and_consent_required_after_disconnect(self):
        archive = dict(namespace='a'*32, digest='b'*64, scenario=0, difficulty=1,
                       saved_at='2026-11-27 12:00:00')
        source = Mock()
        source.resolve_checkpoint.side_effect = lambda choice: choice['digest']
        host = LobbyHost('session', 'host', 'guest', catalog=Mock(), load_source=source,
                         settings={'coop_checkpoint': archive})
        guest = LobbyGuest('host', 'guest')
        host.connect()

        def deliver():
            self.assertTrue(guest.receive(host.snapshot(), 'session'))

        def start():
            rev = host.lobby.revision
            proof = (rev, archive['namespace'], archive['digest'])
            host.checkpoint_proof = guest.checkpoint_proof = proof
            deliver()
            consent = guest.ready_message(True, campaign_consent=True)
            consent = decode(encode(consent, steam_pose=True), steam_pose=True)
            with self.assertRaises(ValueError):
                host.set_ready('guest', True, rev, checkpoint_identity='0'*64, campaign_consent=True)
            host.set_ready('guest', True, rev, checkpoint_identity=consent['checkpoint_identity'], campaign_consent=True)
            host.set_ready('host', True, rev)
            host.check_load(rev, start_campaign=True)
            deliver()
            ack = guest.load_ack(source)
            self.assertTrue(host.acknowledge_load(ack))
            deliver()
            self.assertTrue(host.acknowledge_load(guest.load_ack(source, stage_id='1'*32)))
            self.assertTrue(host.begin_start('2'*32))
            deliver()
            self.assertIsNotNone(guest.start_deadline(guest.current_message(), '1'*32))
            check = guest.message['data']['load_check']
            self.assertEqual((check['checkpoint_version'], check['save_digest']), (1, archive['digest']))
            return ack

        old = start()
        host.disconnect()
        guest.reset_link()
        host.connect()
        self.assertNotIn('coop_checkpoint', host.lobby.settings)
        host.lobby.configure('host', coop_checkpoint=archive)
        deliver()
        self.assertFalse(any(guest.message['data']['ready'].values()))
        with self.assertRaises(ValueError):
            guest.ready_message(True, campaign_consent=True)
        with self.assertRaises(ValueError):
            host.set_ready('host', True, host.lobby.revision)
        new = start()
        self.assertNotEqual(old['attempt_id'], new['attempt_id'])
        self.assertFalse(host.acknowledge_load(old))
        host.catalog.select.assert_not_called()

    def test_two_bridge_loops_start_from_host_archive_with_empty_guest(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        stop, advertisement = Event(), Event()
        queues, errors, workers = [Queue(), Queue()], Queue(), []
        peers, stages, transfers = [], {}, {}
        allow_guest_stage = Event()
        for i, role in enumerate((b'H', b'G')):
            directory = root/'userdata'/str(i+100)/'883710'/'remote'/'win64_save'
            directory.mkdir(parents=True)
            peer = Peer(role, i+100, directory, queues[i], queues[1-i], advertisement)
            peer.data = root/role.decode()
            peer.data.mkdir()
            peers.append(peer)
        archive = HostArchive(peers[0].directory, 'a'*32)
        archive.source.mkdir()
        before = archive.before_save()
        for name in FILES:
            (archive.source/name).write_bytes(name.encode())
        digest = archive.publish(before, {'attempt': 'b'*32, 'release': 'c'*32, 'slot': 0,
                                 'scenario': 0, 'difficulty': 1, 'timestamp': '639000000000000000'}, lambda: None)
        choice = {'namespace': archive.namespace, 'digest': digest}

        # The native Steam pipe, archive I/O on the guest and RE2's staged
        # receipt are the boundaries of this two-lobby integration test.
        class NativeController:
            ready = True
            error = request_id = None
            cancelled_at = None

            @property
            def finished(self):
                return self.cancelled_at is not None and monotonic() - self.cancelled_at > .4

            def __init__(self, data, pid, role, stop, selection, membership):
                self.role = role
                self.data = data
                self.source = Mock()
                self.source.resolve_checkpoint.side_effect = lambda choice: choice['digest']
                self.source.directory = self.source.supplied_directory = peers[pid-100].directory
                self.selection = selection

            def start(self):
                pass

            def stage(self, attempt):
                if self.role in stages and stages[self.role][0] == attempt:
                    raise AssertionError('duplicate native stage')
                self.request_id = ('1' if self.role == b'H' else '2')*32
                stages[self.role] = (attempt, self.request_id)

            def staged(self, stage_id, *, releasing):
                return stage_id == self.request_id

            def cancel(self):
                if self.cancelled_at is None:
                    self.cancelled_at = monotonic()

            close = cancel

        def native_stage(data, message, role, pid, membership):
            if role == 'G' and not allow_guest_stage.is_set():
                return None
            if stages.get(role.encode(), (None,))[0] != (message['data'].get('load_check') or {}).get('attempt_id'):
                return None
            return stages.get(role.encode(), (None, None))[1]

        def run(peer):
            def exchange(scope, nonce, stop):
                transfers[peer.role] = (scope['choice']['digest'], nonce)
                return choice.copy()
            try:
                run_bridge(peer.data, peer, peer.role, 'h', 'g', stop=stop, lobby_enabled=True,
                           save_catalog=SaveCatalog(peer.data/'re2_coop_save_catalog.json'),
                           exchange_checkpoint=exchange)
            except BaseException as exc:
                errors.put(exc)

        def wait(peer, predicate):
            limit, last = monotonic()+12, None
            while monotonic() < limit:
                if not errors.empty():
                    raise errors.get()
                try:
                    last = json.loads((peer.data/'re2_coop_lobby.json').read_bytes())
                except (OSError, ValueError):
                    pass
                if last and predicate(last):
                    return last
                sleep(.025)
            self.fail(f'{peer.role}: {last}')

        for key in ('CHECK_INTERVAL', 'LOBBY_INTERVAL', 'RETRY_INTERVAL'):
            self.enterContext(patch('steam_pose_bridge.'+key, .1))
        self.enterContext(patch('lobby_sync._packaged_commit', return_value='f'*40))
        self.enterContext(patch('checkpoint_start.CheckpointStartController', NativeController))
        self.enterContext(patch('steam_pose_bridge.read_staged_load', native_stage))
        self.enterContext(patch('steam_pose_bridge.storage_guard_active', return_value=True))
        try:
            for peer in peers:
                worker = Thread(target=run, args=(peer,))
                workers.append(worker)
                worker.start()
            host, guest = peers
            wait(host, lambda s: s['connected'])
            submit(host.data, 'select-checkpoint', choice)
            for peer in peers:
                wait(peer, lambda s: s.get('checkpoint_status') == 'ready')
            self.assertEqual(transfers[b'H'], transfers[b'G'])
            submit(host.data, 'ready', True)
            submit(guest.data, 'ready-campaign', True)
            wait(host, lambda s: s.get('campaign_start_ready'))
            submit(host.data, 'start-campaign', True)
            wait(host, lambda s: b'H' in stages and b'G' in stages)
            previous_attempt = stages[b'H'][0]
            submit(host.data, 'cancel-load-check', True)
            wait(host, lambda s: s.get('checkpoint_status') == 'failed')
            submit(host.data, 'select-checkpoint', choice)
            for peer in peers:
                wait(peer, lambda s: s.get('checkpoint_status') == 'ready' and
                     not any(s['lobby']['data']['ready'].values()))
            allow_guest_stage.set()
            submit(host.data, 'ready', True)
            submit(guest.data, 'ready-campaign', True)
            wait(host, lambda s: s.get('campaign_start_ready'))
            submit(host.data, 'start-campaign', True)
            for peer in peers:
                state = wait(peer, lambda s: s.get('prepared_start'))
                self.assertEqual(state['prepared_start']['id'], stages[peer.role][1])
                self.assertEqual(state['lobby']['data']['load_check']['save_digest'], digest)
            self.assertEqual(stages[b'H'][0], stages[b'G'][0])
            self.assertNotEqual(previous_attempt, stages[b'H'][0])
            self.assertEqual(list(guest.directory.iterdir()), [])
            revision = state['lobby']['data']['revision']
            submit(host.data, 'select-checkpoint', choice)
            rejected = wait(host, lambda s: 'bereits geladen' in (s.get('error') or ''))
            self.assertEqual(rejected['lobby']['data']['revision'], revision)
            from tests.test_steam_pose_bridge import sample
            dropped = Event()
            original_send = host.send
            def lose_first_pose(message):
                if message['type'] == 'event' and not dropped.is_set():
                    dropped.set()
                else:
                    original_send(message)
            with patch.object(host, 'send', lose_first_pose):
                for seq in (1, 2):
                    write_json(host.data/'re2_coop_observer.json', {
                        **sample(seq, [1, 2, seq]), 'schema': 1, 'source': 're2',
                        'observed_at': int(time()), 'available': True})
                    if seq == 1:
                        self.assertTrue(dropped.wait(3))
                def restored(status):
                    pose_path = guest.data/'re2_coop_guest_pose.json'
                    pose = json.loads(pose_path.read_bytes()).get('pose') if pose_path.exists() else None
                    return pose and pose['position'] == [1, 2, 2]
                result = wait(guest, restored)
                self.assertEqual(result['lobby']['data']['revision'], revision)
                self.assertEqual(result['lobby']['data']['load_check']['attempt_id'], stages[b'G'][0])
        finally:
            stop.set()
            for worker in workers:
                worker.join(4)
                self.assertFalse(worker.is_alive())
            if not errors.empty():
                raise errors.get()
