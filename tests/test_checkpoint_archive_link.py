"""Two Steam control links driving one archive exchange per current selection."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
import unittest

from protocol import v1
from checkpoint_archive_link import CheckpointArchiveLink


class ArchiveLinkTests(unittest.TestCase):
    def setUp(self):
        self.pool = self.enterContext(ThreadPoolExecutor(max_workers=2))
        self.scope = ('1'*32, '2'*32)
        self.choice = {'digest': '3'*64, 'namespace': '4'*32, 'scenario': 0, 'difficulty': 1,
                       'saved_at': '2026-11-27 01:02:03'}
        self.lobby = {'session_id': self.scope[0], 'data': {'connected': True, 'revision': 2,
                      'save_slot': None, 'settings': {'coop_checkpoint': self.choice}}}
        self.calls = []
        self.build = 'a'*40
        self.block = Event()
        self.block.set()

    def link(self, role, build=None):
        def exchange(scope, nonce, stop):
            self.calls.append((scope, nonce, stop))
            while not self.block.is_set() and not stop.wait(.01):
                pass
            return {k: self.choice[k] for k in ('namespace', 'digest')}
        link = CheckpointArchiveLink(role, build or self.build, exchange, self.pool)
        self.addCleanup(link.clear)
        self.bind(link)
        return link

    def bind(self, link):
        membership = {'session_id': 'd'*32, 'revision': 7 if link.role == b'H' else 9}
        link.bind(self.scope, b'epoch001', membership, self.lobby)

    def wire(self, link, message, now):
        replies = []
        link.tick(lambda m: replies.append(v1.decode(v1.encode(m, steam_pose=True), steam_pose=True)), message, now)
        return replies[-1] if replies else None

    def complete_exchange(self):
        host, guest = self.link(b'H'), self.link(b'G')
        g = None
        now = monotonic()
        for _ in range(100):
            now += 1
            h = self.wire(host, g, now)
            g = self.wire(guest, h, now)
            sleep(.002)
            if host.transferred and guest.transferred:
                break
        self.assertTrue(host.transferred and guest.transferred)
        return host, guest, h, g, now

    def test_roles_use_one_negotiated_nonce_and_advertise_preparation_only_after_transfer(self):
        host, guest, h, g, now = self.complete_exchange()
        self.assertEqual(2, len(self.calls))
        self.assertEqual(self.calls[0][1], self.calls[1][1])
        self.assertFalse(host.peer_prepared(now))
        guest.local_prepared = True
        proof = self.wire(guest, h, now+1)
        self.wire(host, proof, now+1)
        self.assertTrue(host.peer_prepared(now+1))
        self.wire(host, proof, now+10)
        self.assertFalse(host.peer_prepared(now+10))
        self.lobby['data']['revision'] += 1
        self.bind(host)
        self.wire(host, proof, now+11)
        self.assertFalse(host.transferred or host.local_prepared or host.peer_prepared(now+11))

    def test_mismatched_build_and_old_echo_cannot_start_a_worker(self):
        host, guest = self.link(b'H'), self.link(b'G', 'b'*40)
        now = monotonic()
        h = self.wire(host, None, now)
        g = self.wire(guest, h, now)
        self.wire(host, g, now+1)
        self.assertEqual(self.calls, [])
        self.assertFalse(host.transferred or guest.transferred)
        other = self.link(b'G')
        echo = self.wire(other, h, now+1)
        host.clear()
        self.bind(host)
        self.wire(host, echo, now+2)
        self.assertEqual(self.calls, [])

    def test_remote_rebind_with_unchanged_host_selection_withdraws_previous_transfer(self):
        host, guest, h, g, now = self.complete_exchange()
        guest.local_prepared = True
        g = self.wire(guest, h, now+1)
        self.wire(host, g, now+1)
        self.assertTrue(host.peer_prepared(now+1))
        replacement = self.link(b'G')
        hello = self.wire(replacement, None, now+2)
        self.wire(host, hello, now+2)
        self.assertFalse(host.transferred or host.peer_prepared(now+2))

    def test_failure_after_transfer_revokes_local_and_remote_readiness(self):
        host, guest, h, g, now = self.complete_exchange()
        host.local_prepared = guest.local_prepared = True
        host.fail('Lokaler Import abgelaufen.')
        host.fail('Späterer Fehler.')
        h = self.wire(host, g, now+1)
        self.wire(guest, h, now+1)
        self.assertEqual(host.error, 'Lokaler Import abgelaufen.')
        self.assertTrue(guest.error)
        self.assertNotIn(host.error, str(h))
        self.assertFalse(guest.local_prepared or guest.transferred or host.transferred)
        self.assertEqual(len(self.calls), 2)

    def test_busy_includes_cancelled_worker_until_it_releases_the_snapshot_lane(self):
        release, entered = Event(), Event()
        self.addCleanup(release.set)
        def exchange(scope, nonce, stop):
            entered.set()
            release.wait(2)
            return {k: scope['choice'][k] for k in ('namespace', 'digest')}
        host = CheckpointArchiveLink(b'H', self.build, exchange, self.pool)
        self.addCleanup(host.clear)
        self.bind(host)
        guest = self.link(b'G')
        now = monotonic()
        h = self.wire(host, None, now)
        g = self.wire(guest, h, now)
        self.wire(host, g, now+1)
        self.assertTrue(entered.wait(1))
        host.clear()
        self.assertTrue(host.busy)
        release.set()
        limit = monotonic()+1
        while host.busy and monotonic() < limit:
            sleep(.002)
        self.assertFalse(host.busy or host.transferred)

    def test_selection_switch_cancels_running_exchange_and_discards_its_late_result(self):
        self.block.clear()
        self.addCleanup(self.block.set)
        host, guest = self.link(b'H'), self.link(b'G')
        now = monotonic()
        h = self.wire(host, None, now)
        g = self.wire(guest, h, now)
        h = self.wire(host, g, now+1)
        self.wire(guest, h, now+1)
        limit = monotonic()+1
        while len(self.calls) < 2 and monotonic() < limit:
            sleep(.002)
        self.assertEqual(len(self.calls), 2)
        self.lobby['data']['revision'] += 1
        self.bind(host)
        self.bind(guest)
        self.assertTrue(all(stop.is_set() for _, _, stop in self.calls))
        self.wire(host, g, now+2)
        self.assertFalse(host.transferred)


class ProtectedExchangeTests(unittest.TestCase):
    def test_normal_steam_title_secures_profile_before_opening_snapshot_lane(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from campaign_setup import CampaignSetup
        from steam_pose_bridge import SteamPipe
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        solo = root / 'remote/win64_save'
        solo.mkdir(parents=True)
        setup = CampaignSetup(root, SteamPipe(71), Event())
        member = {'session_id': 'c'*32, 'revision': 6}
        choice = {'namespace': 'a'*32, 'digest': 'b'*64, 'scenario': 0, 'difficulty': 1,
                  'saved_at': '2026-11-27 12:34:56'}
        scope = {'session_id': 'd'*32, 'request_id': '0'*32, 'revision': 2, 'choice': choice, 'epoch': b'epoch001',
                 'role': 'G', 'membership': member}
        published = {'session_id': scope['session_id'], 'membership': member, 'role': 'G', 'game_pid': 71}
        lobby = {'revision': 2, 'settings': {'coop_checkpoint': choice}, 'save_slot': None}
        guard = {'checkpoint_supported': False, 'in_title': True, 'busy': False, 'loading_flow': False,
                 'has_player': False, 'allowed_load_calls': 0, 'denied_loads': 0, 'writes': {}}
        native = SteamPipe(71, stream='snapshot')
        native.save_directory = lambda: solo
        native.membership_revision = lambda: 6
        native.cloud_status = lambda: 'cloud-app-disabled'
        native.lobby_status = lambda: 'joined'
        trace = []
        native.protect_campaign = lambda: trace.append('native guard')
        setup._ensure_live_guard = lambda directory: trace.append('ACL')
        selection = {k: choice[k] for k in ('namespace','digest')}
        self.enterContext(patch('steam_pose_bridge.SteamPipe', return_value=native))
        self.enterContext(patch('campaign_setup._steam_for_save', return_value=None))
        self.enterContext(patch('readonly_save_control.read_connected_lobby', return_value=(published, lobby)))
        def active_guard(*args, **kwargs):
            if 'native guard' not in trace:
                raise FileNotFoundError('A normal Steam launch has no active Lua report before protect-campaign')
            return {**guard, 'runtime_protection': True, 'protection': {'game_pid': 71}}
        self.enterContext(patch('readonly_save_control.read_active_guard', side_effect=active_guard))
        # The transfer layer independently exercises all snapshot frames and file publication in its own suite.
        class Binding:
            def __init__(self, data, pipe, directory, selected, role):
                assert (data, pipe, directory, selected, role) == (root, native, solo, selection, b'G')
                self.scope, self.revision, self.choice = published, 2, choice
            def exchange(self, nonce, *, stop):
                trace.append(nonce)
                return selection
        self.enterContext(patch('checkpoint_transfer_binding.ArchiveTransferBinding', Binding))
        self.assertEqual(setup.exchange_checkpoint(scope, 'e'*32, Event()), selection)
        self.assertEqual(trace, ['ACL', 'native guard', 'e'*32])
        trace.clear()
        lobby['revision'] = 3
        with self.assertRaises(ValueError):
            setup.exchange_checkpoint(scope, 'f'*32, Event())
        self.assertEqual(trace, [])
