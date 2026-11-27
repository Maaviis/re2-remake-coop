"""Two production bridge loops and real copy transactions, with simulated Steam and RE2 receipts."""

import json
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import unittest
from unittest.mock import patch

import lobby_sync
from campaign_save_copy import check_managed_save, open_save_session
from campaign_setup import CampaignSetup
from load_preflight import NativeSaveSource
from lobby_control import submit
from lobby_sync import _packaged_commit, write_json
from readonly_save_control import arm
from save_catalog import SaveCatalog
from steam_pose_bridge import _encode, run_automatic_bridge, run_bridge
from tests.test_save_protection import protection_documents, write_protection


class Peer:
    epoch = b'test-epoch'
    lobby_name = 'test-lobby'

    def __init__(self, role, pid, directory, incoming, outgoing, advertise):
        self.role, self.game_pid, self.directory = role, pid, directory
        self.incoming, self.outgoing = incoming, outgoing
        self.advertise = advertise

    def lobby_status(self):
        return 'owned' if self.role == b'H' else 'joined'

    def membership_revision(self):
        return 7

    def save_directory(self):
        return self.directory

    def cloud_status(self):
        return 'cloud-app-disabled'

    def request(self, command, *, pipe_name):
        assert command == b'peer-status' and pipe_name == self.lobby_name
        return b'peer-ready'

    def receive(self):
        try:
            return self.incoming.get_nowait()
        except Empty:
            return None

    def send(self, message):
        if message['type'] != 'new_game_capability' or self.advertise.is_set():
            self.outgoing.put(_encode(message))


class NewGameBridgeTests(unittest.TestCase):
    def wait_status(self, profile, errors, predicate):
        deadline = monotonic() + 8
        state = None
        while monotonic() < deadline:
            if not errors.empty():
                raise errors.get()
            try:
                state = json.loads((profile / 're2_coop_lobby.json').read_text(encoding='utf-8'))
            except (ValueError, OSError):
                state = None
            if state and predicate(state):
                return state
            sleep(.02)
        self.fail(f'bridge {profile.name}: {state}')

    def test_no_scenario_files_on_either_peer(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        wire = [Queue(), Queue()]
        ready = Event()
        stop = Event()
        errors = Queue()
        threads, peers, profiles, requests, originals = [], [], [], [], []
        selection = {'scenario': 'CLAIRE_A', 'difficulty': 'HARD'}
        for i, role in enumerate((b'H', b'G')):
            profile = root / 'userdata' / str(100 + i) / '883710' / 'remote' / 'win64_save'
            profile.mkdir(parents=True)
            original = bytes([65 + i])
            (profile / 'data000.bin').write_bytes(original)
            session = self.enterContext(open_save_session(profile, lambda: None))
            originals.append((session, profile, profile.stat().st_ino, original))
            session.install()
            self.addCleanup(session.restore)
            data = root / role.decode()
            data.mkdir()
            profiles.append(data)
            peers.append(Peer(role, 100+i, profile, wire[i], wire[1-i], ready))

        def run(data, peer):
            def stage(value):
                now = int(time())
                native, launch = protection_documents(now)
                write_protection(data, {**native, 'game_pid': peer.game_pid}, {**launch, 'game_pid': peer.game_pid})
                guard = {'schema': 1, 'active': True, 'at': now, 'hooks': 26, 'protection_active': True,
                         'protection': {'game_pid': peer.game_pid, 'run_id': native['run_id']},
                         'guard_run_id': peer.role.decode(), 'command_id': '', 'command_error': '', 'load_request_id': '',
                         'new_game_supported': True, 'allowed_load_calls': 0, 'denied_loads': 0}
                path = data / 're2_coop_save_guard.json'
                write_json(path, guard)
                request = arm(data, value, None, load=True, require_receipt=True, prepared_lobby=peer.directory,
                              expected_game_pid=peer.game_pid, expected_role=peer.role.decode())
                policy = json.loads((data / 're2_coop_save_policy.json').read_text())
                write_json(path, {**guard, 'staged_load': {'id': request, 'requested_at': policy['at']}})
                requests.append(policy)
                return request

            stage.supports_new_game = True
            try:
                source = NativeSaveSource(data, peer.directory, allow_date=None, managed=True)
                run_bridge(data, peer, peer.role, 'host', 'guest', stop=stop, lobby_enabled=True,
                           save_catalog=source.catalog, load_source=source, stage_campaign=stage)
            except BaseException as exc:
                errors.put(exc)

        def wait(i, predicate):
            return self.wait_status(profiles[i], errors, predicate)

        for name in ('RETRY_INTERVAL', 'LOBBY_INTERVAL', 'CHECK_INTERVAL'):
            self.enterContext(patch('steam_pose_bridge.' + name, .1))
        self.enterContext(patch('readonly_save_control.SteamPipe', side_effect=lambda pid: peers[pid-100]))
        self.enterContext(patch('readonly_save_control._storage_guard_active', return_value=True))
        self.enterContext(patch('steam_pose_bridge.storage_guard_active', return_value=True))
        try:
            for data, peer in zip(profiles, peers):
                threads.append(Thread(target=run, args=(data, peer)))
                threads[-1].start()
            wait(0, lambda s: s.get('campaign_peer_supported'))
            with self.assertRaisesRegex(ValueError, 'both peers'):
                submit(profiles[0], 'select-new-game', selection)
            ready.set()
            wait(0, lambda s: s.get('new_game_supported'))
            submit(profiles[0], 'select-new-game', selection)
            for i in (0, 1):
                wait(i, lambda s: (s.get('lobby') or {}).get('data', {}).get('new_game') == selection)
            submit(profiles[0], 'ready', True)
            submit(profiles[1], 'ready-campaign', True)
            wait(0, lambda s: s.get('campaign_start_ready'))
            submit(profiles[0], 'start-campaign', True)
            for i in (0, 1):
                state = wait(i, lambda s: s.get('prepared_start'))
                self.assertIsNone(state['lobby']['data']['save_slot'])
                self.assertEqual(list(p.name for p in peers[i].directory.iterdir()), ['data000.bin'])
            self.assertEqual(len(requests), 2)
            self.assertEqual(len({p['lobby_load']['attempt_id'] for p in requests}), 1)
            for policy in requests:
                self.assertEqual(policy['schema'], 4)
                self.assertEqual(policy['new_game'], selection)
                self.assertNotIn('reference', policy)
            guest_id = next(p['id'] for p in requests if p['lobby_load']['role'] == 'G')
            guard_path = profiles[1] / 're2_coop_save_guard.json'
            guard = json.loads(guard_path.read_text())
            guard.update(command_id=guest_id, load_request_id=guest_id, load_phase='closing_menu')
            write_json(guard_path, guard)
            wait(1, lambda s: (profiles[1] / 're2_coop_lobby_view.json').is_file())
            write_json(guard_path, {**guard, 'load_phase': 'failed', 'load_error': 'new_game_title_changed'})
            wait(1, lambda s: 'new_game_title_changed' in (s.get('error') or ''))
            wait(0, lambda s: s['lobby']['data']['ready']['guest'] is False)
        finally:
            stop.set()
            for worker in threads:
                worker.join(4)
                self.assertFalse(worker.is_alive())
            if not errors.empty():
                raise errors.get()
        for session, directory, original_id, original_bytes in originals:
            session.restore()
            self.assertEqual(directory.stat().st_ino, original_id)
            self.assertEqual([p.name for p in directory.iterdir()], ['data000.bin'])
            self.assertEqual((directory / 'data000.bin').read_bytes(), original_bytes)

    def test_installed_direct_prepare_requires_equal_builds_and_stages_both_games(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        package_commit = _packaged_commit()
        if package_commit is None:
            # Source checkouts have no bundle manifest. In a packaged run the
            # real LobbyFiles reader and the installed build-info.json are used.
            self.assertEqual(Path(lobby_sync.__file__).resolve().parent, Path(__file__).resolve().parents[1] / "bridge",
                             'installed package has no valid source commit')
            package_commit = 'a' * 40
            self.enterContext(patch('lobby_sync._packaged_commit', return_value=package_commit))
        stop, errors = Event(), Queue()
        queues, peers, threads = [Queue(), Queue()], [], []
        selection = {'scenario': 'CLAIRE_A', 'difficulty': 'HARD'}
        for i, role in enumerate((b'H', b'G')):
            save = root / 'userdata' / str(100 + i) / '883710' / 'remote' / 'win64_save'
            save.mkdir(parents=True)
            (save / 'data00-1.bin').write_bytes(role)
            self.assertFalse(check_managed_save(save))
            data = root / role.decode()
            data.mkdir()
            peers.append(DirectPeer(role, 100+i, save, queues[i], queues[1-i], data))

        def guarded(func, *args):
            try:
                func(*args)
            except BaseException as exc:
                errors.put(exc)

        def run(peer):
            setup = CampaignSetup(peer.data, peer, stop)
            run_automatic_bridge(peer.data, peer, 'host', 'guest', stop=stop,
                                 save_catalog=SaveCatalog(peer.data/'re2_coop_save_catalog.json'),
                                 prepare_new_campaign=setup.enable_new)

        # External Steam/RE2/Windows boundaries only. Verification ends at
        # two staged commands and subsequent cutscene exchange. RE2 callbacks
        # and Steam packets are simulated here. No gameplay release is issued.
        for name in ('campaign_setup.storage_guard_active', 'save_protection.storage_guard_active',
                     'steam_pose_bridge.storage_guard_active', 'readonly_save_control._storage_guard_active'):
            self.enterContext(patch(name, return_value=True))
        self.enterContext(patch('campaign_setup._steam_for_save', return_value=(root/'steam.exe', root/'userdata')))
        self.enterContext(patch('readonly_save_control.SteamPipe', side_effect=lambda pid: peers[pid-100]))
        self.enterContext(patch('campaign_start._confirm_loaded_campaign'))
        for name in ('RETRY_INTERVAL', 'LOBBY_INTERVAL', 'CHECK_INTERVAL'):
            self.enterContext(patch('steam_pose_bridge.'+name, .1))
        host, guest = peers
        def wait(peer, condition):
            return self.wait_status(peer.data, errors, condition)
        try:
            for peer in peers:
                for func, args in [(peer.publish_receipts, (stop,)), (run, (peer,))]:
                    worker = Thread(target=guarded, args=(func, *args))
                    threads.append(worker)
                    worker.start()
            for peer in peers:
                state = wait(peer, lambda s: s.get('direct_campaign_available') and s['connected'])
                self.assertEqual(state['source_commit'], package_commit)
                self.assertFalse(state.get('new_game_supported'))
            # Only the host clicks New Game. A different advertised package
            # must never mount a guest folder, even on an authenticated link.
            host.override_commit = '0' * 40 if package_commit != '0' * 40 else '1' * 40
            submit(host.data, 'prepare-new-campaign', True)
            wait(host, lambda s: s.get('campaign_start_supported') and host.advertised)
            self.assertIsNone(guest.token)
            wait(host, lambda s: s.get('guest_preparation') == 'package_mismatch')
            guest.reject_mount = True
            guest.foreground = False
            host.override_commit = None
            wait(host, lambda s: s.get('guest_preparation') == 'guest_window')
            self.assertIsNone(guest.token)
            guest.cloud = 'cloud-enabled'
            guest.foreground = True
            for peer in peers:
                wait(peer, lambda s: s.get('guest_preparation') == 'cloud_enabled')
            self.assertIsNone(guest.token)
            guest.cloud = 'cloud-app-disabled'
            wait(guest, lambda s: s.get('error') and s.get('direct_campaign_available'))
            wait(host, lambda s: s.get('guest_preparation') == 'guest_error')
            def host_received_guest_error(status):
                session = status['lobby']['session_id']
                timeline = host.data/'re2_coop_logs'/session/'timeline.jsonl'
                try:
                    rows = [json.loads(line) for line in timeline.read_text(encoding='utf-8').splitlines()]
                except (OSError, ValueError):
                    return False
                return (any(row['role'] == 'Host' for row in rows)
                        and any(row['role'] == 'Gast' and row['component'] == 'ERROR'
                                and 'prepare_new_game' in row['detail'] for row in rows))
            wait(host, host_received_guest_error)
            self.assertIsNone(guest.token)
            host_token = host.token
            guest.reject_mount = False
            submit(host.data, 'prepare-new-campaign', True)
            for peer in peers:
                wait(peer, lambda s: s.get('new_game_supported') and not s.get('error'))
                self.assertEqual(peer.advertised, (2, package_commit))
                self.assertRegex(peer.token, '^[a-f0-9]{32}$')
            self.assertEqual(host.token, host_token)
            self.assertNotEqual(host.token, guest.token)
            # Two generations can share native autosave slot zero. Select by archive identity.
            from coop_checkpoint import FILES, HostArchive
            archive = HostArchive(host.directory, 'd' * 32)
            archive.source.mkdir()
            before = archive.before_save()
            for filename in FILES:
                (archive.source / filename).write_bytes(b'host checkpoint')
            digest = archive.publish(before, dict(attempt='a'*32, release='b'*32, slot=0, scenario=0,
                                                  difficulty=1, timestamp='639000000000000000'), lambda: None)
            choice = {'namespace': archive.namespace, 'digest': digest}
            with self.assertRaisesRegex(ValueError, 'only the host'):
                submit(guest.data, 'select-checkpoint', choice)
            submit(host.data, 'select-checkpoint', choice)
            for peer in peers:
                state = wait(peer, lambda s: s['lobby']['data']['settings'].get('coop_checkpoint', {}).get('digest') == digest)
                self.assertFalse(any(state['lobby']['data']['ready'].values()))
                self.assertFalse((peer.data/'re2_coop_save_policy.json').exists())
            submit(host.data, 'select-new-game', selection)
            for peer in peers:
                wait(peer, lambda s: (s.get('lobby') or {}).get('data', {}).get('new_game') == selection)
            submit(host.data, 'ready', True)
            submit(guest.data, 'ready-campaign', True)
            wait(host, lambda s: s.get('campaign_start_ready'))
            guest.override_commit = '0' * 40 if package_commit != '0' * 40 else '1' * 40
            mismatched = wait(host, lambda s: not s.get('new_game_supported'))
            self.assertFalse(mismatched.get('campaign_start_ready'))
            self.assertTrue(mismatched['connected'])
            submit(host.data, 'start-campaign', True)
            wait(host, lambda s: s.get('error'))
            for peer in peers:
                self.assertFalse((peer.data/'re2_coop_save_policy.json').exists())
            guest.override_commit = None
            wait(host, lambda s: s.get('campaign_start_ready'))
            submit(host.data, 'start-campaign', True)
            policies = []
            for peer in peers:
                state = wait(peer, lambda s: s.get('prepared_start'))
                policy = json.loads((peer.data/'re2_coop_save_policy.json').read_text())
                self.assertEqual(policy['schema'], 4)
                self.assertEqual(policy['new_game'], selection)
                self.assertNotIn('reference', policy)
                self.assertEqual(policy['protection'], peer.binding())
                self.assertEqual(state['prepared_start']['id'], policy['id'])
                self.assertIsNone(state['lobby']['data']['save_slot'])
                self.assertEqual([p.name for p in peer.directory.iterdir()], ['data00-1.bin'])
                self.assertEqual((peer.directory/'data00-1.bin').read_bytes(), peer.role)
                self.assertFalse(check_managed_save(peer.directory))
                policies.append(policy)
            self.assertEqual(policies[0]['lobby_load']['attempt_id'], policies[1]['lobby_load']['attempt_id'])
            self.assertNotEqual(policies[0]['id'], policies[1]['id'])
            attempt = policies[0]['lobby_load']['attempt_id']
            scene = dict(event='evt_20011', occurrence=1, phase='waiting', vote=0, decision='none')
            def peer_view(peer):
                path = peer.data/'re2_coop_cutscene_peer.json'
                try:
                    return json.loads(path.read_bytes())
                except (OSError, ValueError):
                    return {}
            for peer in peers:
                wait(peer, lambda s: peer_view(peer).get('attempt_id') == attempt)
                view = peer_view(peer)
                self.assertEqual(view.get('attempt_id'), attempt)
                self.assertIsNone(view['peer'])
                peer.scene = scene.copy()
                peer.native_start.set()
            for peer in peers:
                wait(peer, lambda s: peer_view(peer).get('peer') == scene)
            host.scene = {**scene, 'phase': 'playing', 'vote': 1, 'decision': 'request'}
            wait(guest, lambda s: peer_view(guest).get('peer') == host.scene)
            guest.scene = {**host.scene, 'decision': 'decline'}
            wait(host, lambda s: peer_view(host).get('peer') == guest.scene)
            wait(host, lambda s: s['lobby']['data']['load_check']['reason'] == 'start_window_expired')
            host.scene = {**host.scene, 'vote': 2}
            wait(guest, lambda s: peer_view(guest).get('peer') == host.scene)
            guest.scene = {**host.scene, 'decision': 'accept', 'phase': 'ended'}
            wait(host, lambda s: peer_view(host).get('peer') == guest.scene)
            host.scene = {**host.scene, 'phase': 'ended'}
            wait(guest, lambda s: peer_view(guest).get('peer') == host.scene)
            old_tokens = [peer.token for peer in peers]
            # A lost pose during the movie transition must not masquerade as a new guest.
            from tests.test_steam_pose_bridge import sample
            host.drop_next_pose = True
            for seq in (1, 2):
                write_json(host.data/'re2_coop_observer.json', {
                    **sample(seq, [1, 2, seq]), 'observed_at': int(time()), 'available': True,
                    'schema': 1, 'source': 're2'})
                if seq == 1:
                    wait(host, lambda s: not host.drop_next_pose)
            def guest_pose_restored(status):
                try:
                    pose = json.loads((guest.data/'re2_coop_guest_pose.json').read_bytes()).get('pose')
                except (FileNotFoundError, PermissionError):
                    return False
                return pose and pose['position'] == [1, 2, 2]
            wait(guest, guest_pose_restored)
            self.assertEqual([peer.token for peer in peers], old_tokens)
            self.assertFalse(any((peer.data/'re2_coop_campaign_binding_loss.json').exists() for peer in peers))
            scene = {**scene, 'event': 'evt_10001'}
            for peer in peers:
                peer.scene = scene.copy()
            for peer in peers:
                wait(peer, lambda s: peer_view(peer).get('peer') == scene)
            host.scene = {**scene, 'vote': 1, 'decision': 'request', 'phase': 'playing'}
            wait(guest, lambda s: peer_view(guest).get('peer') == host.scene)
            guest.scene = {**host.scene, 'decision': 'accept', 'phase': 'ended'}
            wait(host, lambda s: peer_view(host).get('peer') == guest.scene)
            host.scene = {**host.scene, 'phase': 'ended'}
            wait(guest, lambda s: peer_view(guest).get('peer') == host.scene)
            self.assertEqual([peer.token for peer in peers], old_tokens)
            for peer in peers:
                peer.epoch = b'new-epoch'
            for peer in peers:
                wait(peer, lambda s: s.get('direct_campaign_available') and not peer_view(peer))
            submit(host.data, 'prepare-new-campaign', True)
            for peer, old in zip(peers, old_tokens):
                wait(peer, lambda s: s.get('new_game_supported'))
                self.assertNotEqual(peer.token, old)
                self.assertFalse(peer_view(peer))
        finally:
            stop.set()
            for worker in threads:
                worker.join(5)
                self.assertFalse(worker.is_alive())
            if not errors.empty():
                raise errors.get()


class DirectPeer(Peer):
    """Simulated Steam transport and native/Lua receipts, one per test PID."""

    def __init__(self, role, pid, directory, incoming, outgoing, data):
        super().__init__(role, pid, directory, incoming, outgoing, Event())
        self.data = data
        self.token = self.advertised = self.override_commit = None
        self.reject_mount = False
        self.foreground = True
        self.cloud = 'cloud-app-disabled'
        self.native_start, self.scene = Event(), None
        self.drop_next_pose = False

    def current_campaign(self, revision):
        assert revision == self.membership_revision()
        return self.token

    def preparation_window_active(self):
        return self.foreground

    def cloud_status(self):
        return self.cloud

    def prepare_new_game(self, revision, token):
        assert revision == self.membership_revision() and self.token is None
        if self.reject_mount:
            raise ValueError("Test: Gast befindet sich außerhalb des Titelmenüs.")
        self.token = token

    def revoke_new_game(self, token):
        if token == self.token:
            self.token = None

    def binding(self):
        return {'run_id': f'{self.game_pid:032x}', 'game_pid': self.game_pid, 'campaign_namespace': self.token}

    def send(self, message):
        if self.drop_next_pose and message['type'] == 'event':
            self.drop_next_pose = False
            return
        if message['type'] == 'new_game_capability':
            self.advertised = (message['start_version'], message.get('package_commit'))
            if self.override_commit:
                message = {**message, 'package_commit': self.override_commit}
        self.outgoing.put(_encode(message))

    def publish_receipts(self, stop):
        while not stop.wait(.1):
            binding = self.binding()
            if not binding['campaign_namespace']:
                continue
            now = int(time())
            native, _ = protection_documents(now)
            write_json(self.data/'re2_coop_native_save_guard.json', {**native, **binding,
                       'runtime_locked_files': 1, 'runtime_save_path': str(self.directory)})
            guard = dict(schema=1, active=True, at=now, hooks=26, protection_active=True,
                         protection=binding, campaign_mount_ready=binding['campaign_namespace'],
                         guard_run_id=self.role.decode(), command_id='', command_error='', load_request_id='',
                         new_game_supported=True, allowed_load_calls=0,
                         denied_loads=0, in_title=True, has_player=False, title_open=True, busy=False, load_menu_busy=False)
            try:
                policy = json.loads((self.data/'re2_coop_save_policy.json').read_text())
            except (FileNotFoundError, PermissionError):
                # Windows may temporarily deny the read during atomic replacement.
                # Only the next successful read can acknowledge the staged policy.
                pass
            else:
                if policy['protection'] == binding:
                    if self.native_start.is_set():
                        guard.update(command_id=policy['id'], policy_id=policy['id'], load_request_id=policy['id'],
                                     prepared_load={'new_game': policy['new_game'], 'scope': policy['lobby_load']},
                                     load_phase='loading', load_error='', in_title=False,
                                     load_hold={'phase': 'waiting_for_scene', 'load_request_id': policy['id']})
                        if self.scene:
                            write_json(self.data/'re2_coop_cutscene_local.json', {**self.scene,
                                       'schema': 1, 'at': now, 'game_pid': self.game_pid,
                                       'attempt_id': policy['lobby_load']['attempt_id']})
                    else:
                        guard['staged_load'] = {'id': policy['id'], 'requested_at': policy['at']}
            write_json(self.data/'re2_coop_save_guard.json', guard)
