"""Two production bridge loops and real copy transactions, with simulated Steam and RE2 receipts."""

import json
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep, time
import unittest
from unittest.mock import patch

from campaign_save_copy import open_save_session
from load_preflight import NativeSaveSource
from lobby_control import submit
from lobby_sync import write_json
from readonly_save_control import arm
from steam_pose_bridge import _encode, run_bridge
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
            deadline = monotonic() + 6
            state = None
            while monotonic() < deadline:
                if not errors.empty():
                    raise errors.get()
                try:
                    state = json.loads((profiles[i] / 're2_coop_lobby.json').read_text(encoding='utf-8'))
                except (ValueError, OSError):
                    state = None
                if state and predicate(state):
                    return state
                sleep(.02)
            self.fail(f'bridge {i}: {state}')

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
