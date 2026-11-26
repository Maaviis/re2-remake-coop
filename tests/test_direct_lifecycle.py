import unittest
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import Mock, patch

from save_catalog import SaveCatalog
from steam_pose_bridge import _encode, envelope, run_bridge


class DirectLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(self.enterContext(TemporaryDirectory()))
        self.stop, self.started, self.finish = Event(), Event(), Event()
        self.binding = {'game_pid': 41, 'run_id': '1' * 32, 'campaign_namespace': '2' * 32}
        self.guard = {'protection': self.binding, 'campaign_mount_ready': '2' * 32}
        catalog = SaveCatalog(self.data / 'unused', new_game_only=True)
        self.source = Mock(campaign_binding=self.binding, catalog=catalog, supplied_directory=self.data)
        self.pipe = Mock(game_pid=41, role=b'H', epoch=b'12345678')
        self.pipe.receive.return_value = None
        self.pipe.lobby_status.return_value = 'owned'
        self.pipe.membership_revision.return_value = 1
        self.pipe.cloud_status.return_value = 'cloud-app-disabled'
        self.pipe.save_directory.return_value = self.data
        self.files = self.enterContext(patch('steam_pose_bridge.LobbyFiles')).return_value
        self.files.command.side_effect = self.command
        self.files.last_link_loss = {}
        self.files.last_status = {}
        self.enterContext(patch('readonly_save_control.read_active_guard', side_effect=lambda *a, **k: self.guard))
        self.acl = self.enterContext(patch('steam_pose_bridge.storage_guard_active', return_value=True))
        self.send_prepare = True
        self.errors = []

    def command(self, *args, **kwargs):
        if self.send_prepare:
            self.send_prepare = False
            return {'id': 'a' * 32, 'action': 'prepare-new-campaign', 'value': True}

    def prepare(self, revision):
        self.started.set()
        if not self.finish.wait(4):
            raise ValueError('timed out in test')
        return self.source, Mock(supports_new_game=True)

    def start(self):
        def run():
            try:
                run_bridge(self.data, self.pipe, b'H', 'host', 'guest', stop=self.stop, lobby_enabled=True,
                           prepare_new_campaign=self.prepare)
            except Exception as exc:
                self.errors.append(exc)
        self.worker = Thread(target=run)
        self.worker.start()
        self.addCleanup(self.close)
        self.assertTrue(self.started.wait(2))

    def close(self):
        self.stop.set()
        self.finish.set()
        self.worker.join(4)
        self.assertFalse(self.worker.is_alive())
        if self.errors:
            raise self.errors[0]

    def wait(self, condition):
        end = monotonic() + 3
        while monotonic() < end:
            if self.errors:
                raise self.errors[0]
            if condition():
                return
            sleep(.025)
        self.fail('expected bridge lifecycle transition')

    def prepared(self):
        return any(c.kwargs.get('campaign_start_supported') is True for c in self.files.publish.call_args_list)

    def test_acl_loss_with_unchanged_membership_revokes_prepared_source(self):
        self.finish.set()
        self.start()
        self.wait(self.prepared)
        self.acl.return_value = False
        self.wait(lambda: self.pipe.revoke_new_game.called)
        self.pipe.revoke_new_game.assert_called_with(self.binding['campaign_namespace'])
        self.wait(lambda: self.files.publish.call_args.kwargs.get('direct_campaign_available') is True)

    def test_lua_readback_drifts_with_unchanged_membership(self):
        self.finish.set()
        self.start()
        self.wait(self.prepared)
        self.guard['campaign_mount_ready'] = '3' * 32
        self.wait(lambda: self.pipe.revoke_new_game.called)

    def test_peer_loss_during_prepare_cannot_publish_completed_result(self):
        self.start()
        self.wait(lambda: self.pipe.receive.call_count >= 3)
        self.pipe.epoch = None
        self.wait(lambda: self.files.last_link_loss.get('reason') == 'native_peer_unavailable')
        self.finish.set()
        self.wait(lambda: self.pipe.revoke_new_game.called)
        self.assertFalse(self.prepared())

    def test_local_pose_pipe_break_preserves_campaign_only_within_existing_peer_lease(self):
        incoming = Queue()
        stall, observed = Event(), Event()
        def receive():
            if stall.is_set():
                observed.set()
                err = OSError("local pipe closed")
                err.winerror = 109
                raise err
            try:
                return incoming.get_nowait()
            except Empty:
                return None
        self.pipe.receive.side_effect = receive
        incoming.put(_encode(envelope('hello', request_id='4' * 32)))
        self.finish.set()
        self.start()
        self.wait(lambda: self.prepared() and any(c.args[1] for c in self.files.publish.call_args_list))
        stall.set()
        self.assertTrue(observed.wait(1))
        stall.clear()
        incoming.put(_encode(envelope('ping', nonce=13)))
        self.wait(lambda: any(c.args[0].get('nonce') == 13 for c in self.pipe.send.call_args_list))
        self.pipe.revoke_new_game.assert_not_called()
        with patch('steam_pose_bridge.PEER_TIMEOUT', .25):
            stall.set()
            self.wait(lambda: self.pipe.revoke_new_game.called)

    def test_shutdown_collects_late_worker_grant(self):
        self.start()
        self.stop.set()
        self.finish.set()
        self.worker.join(4)
        self.pipe.revoke_new_game.assert_called_once_with(self.binding['campaign_namespace'])

    def test_restarted_peer_bridge_same_steam_epoch_retires_its_grant(self):
        incoming = Queue()
        def receive():
            try:
                return incoming.get_nowait()
            except Empty:
                return None
        self.pipe.receive.side_effect = receive
        incoming.put(_encode(envelope('hello', request_id='4' * 32)))
        self.finish.set()
        self.start()
        self.wait(self.prepared)
        incoming.put(_encode(envelope('hello', request_id='5' * 32)))
        self.wait(lambda: self.pipe.revoke_new_game.called)
