import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from campaign_setup import CampaignSetup
from campaign_start import prepare_runtime_campaign
from load_preflight import NativeSaveSource
from steam_pose_bridge import SteamPipe
from sync_model import state_digest
from protocol import v1


class DirectCampaignTests(unittest.TestCase):
    def test_new_game_wire_distinguishes_direct_build_from_legacy_copies(self):
        message = dict(version=1, type="new_game_capability", session_id="a"*32, request_id="b"*32,
                       start_version=2, package_commit="c"*40)
        self.assertEqual(v1.decode(v1.encode(message, steam_pose=True), steam_pose=True), message)
        for invalid in ({**message, "package_commit":""}, {**message, "start_version":1},
                        {k:v for k,v in message.items() if k!="package_commit"}):
            with self.assertRaises(v1.ProtocolError):
                v1.encode(invalid, steam_pose=True)
    def test_pipe_pins_namespace_to_positive_membership_revision(self):
        pipe = SteamPipe(17)
        token = 'a' * 32
        with patch.object(pipe, 'request', return_value=b'accepted prepare-new-game') as request:
            pipe.prepare_new_game(7, token)
            request.assert_called_once_with(('prepare-new-game 7 ' + token).encode(), pipe_name=pipe.lobby_name)
            for revision, key in [(True, token), (0, token), (7, '../' + token), (7, 'A' * 32)]:
                with self.assertRaises(ValueError):
                    pipe.prepare_new_game(revision, key)
            self.assertEqual(request.call_count, 1)

    def test_stale_membership_cannot_start_guard_or_restart_game(self):
        with TemporaryDirectory() as temp:
            pipe = Mock()
            pipe.membership_revision.return_value = 2
            setup = CampaignSetup(Path(temp), pipe, Mock())
            with patch('campaign_setup.start_setup') as restart:
                with self.assertRaisesRegex(ValueError, 'Lobby'):
                    setup.enable_new(1)
                pipe.prepare_new_game.assert_not_called()
                restart.assert_not_called()

    def test_direct_campaign_requires_matching_lua_and_native_namespace(self):
        token = '5' * 32
        binding = {'game_pid': 73, 'run_id': '2' * 32, 'campaign_namespace': token}
        selection = {'scenario': 'LEON_A', 'difficulty': 'NORMAL'}
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            pipe, stop = Mock(game_pid=73), Mock()
            pipe.save_directory.return_value = folder
            pipe.membership_revision.return_value = 1
            pipe.cloud_status.return_value = 'cloud-app-disabled'
            stop.is_set.return_value = False
            receipt = dict(protection=binding, campaign_mount_ready=token, denied_loads=0,
                           allowed_load_calls=0, in_title=True, busy=False, load_menu_busy=False,
                           title_open=True, new_game_supported=True)
            with (patch('readonly_save_control.read_active_guard', return_value=receipt),
                  patch('save_protection.storage_guard_active', return_value=True)):
                source, stage = prepare_runtime_campaign(folder, pipe, None, stop, namespace=token, revision=1)
                self.assertIsInstance(source, NativeSaveSource)
                self.assertTrue(stage.supports_new_game)
                pipe.prepare_new_game.assert_called_once_with(1, token)
                self.assertEqual(source.resolve_new_game(selection), state_digest({'new_game': selection}))
                self.assertEqual(source.catalog.snapshot()['entries'], [])
                receipt['campaign_mount_ready'] = '9' * 32
                with self.assertRaisesRegex(ValueError, 'Koop-Ordner'):
                    source.resolve_new_game(selection)
