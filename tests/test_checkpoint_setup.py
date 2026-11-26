"""Continue preparation uses one verified workspace across native process restarts."""
from copy import deepcopy
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch

from campaign_setup import CampaignSetup
from checkpoint_workspace import selected_archive
from coop_checkpoint import FILES, HostArchive
from lobby_sync import write_json


class CheckpointSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.solo = self.root/'userdata/123/883710/remote/win64_save'
        self.solo.mkdir(parents=True)
        (self.solo/'data00-1.bin').write_bytes(b'original system without scenario')
        self.data = self.root/'bridge'
        self.data.mkdir()
        self.archive = HostArchive(self.solo, 'a'*32)
        self.archive.source.mkdir()
        before = self.archive.before_save()
        for name in FILES:
            (self.archive.source/name).write_bytes(b'checkpoint '+name.encode())
        digest = self.archive.publish(before, dict(attempt='b'*32, release='c'*32,
            slot=0, scenario=0, difficulty=1, timestamp='639000000000000000'), lambda: None)
        self.selection = {'namespace': self.archive.namespace, 'digest': digest}
        _, self.manifest, choice = selected_archive(self.solo, self.selection)
        self.scope = {'game_pid': 32, 'role': 'H', 'session_id': 'd'*32,
                      'membership': {'revision': 7, 'session_id': 'e'*32}}
        self.lobby = {'revision': 2, 'save_slot': None, 'settings': {'coop_checkpoint': choice}}
        self.guard = {'guard_run_id': 'lua', 'in_title': True, 'has_player': False, 'loading_flow': False,
                      'busy': False, 'title_open': True, 'allowed_load_calls': 0, 'denied_loads': 0, 'writes': {}}
        self.current = None
        self.commands, self.mounts, self.revoked = [], [], []
        self.mount_failure = self.after_mount = None
        owner = self

        class Pipe:
            game_pid = 32
            lobby_name = 'fixture'

            def save_directory(self): return owner.solo
            def cloud_status(self): return 'cloud-app-disabled'
            def membership_revision(self): return 7
            def lobby_status(self): return 'owned' if owner.scope['role'] == 'H' else 'joined'
            def current_campaign(self, revision): return owner.current
            def revoke_new_game(self, token): owner.revoked.append(token)
            def prepare_new_game(self, revision, token):
                return owner.mount(owner.data, self, None, owner.stop,
                                   namespace=token, revision=revision, already_bound=False)

            def request(self, command, **kwargs):
                owner.commands.append(command)
                if command.startswith(b'cancel-checkpoint-import '):
                    return b'accepted cancel-checkpoint-import'
                fields = command.decode().split()
                owner.assertEqual(fields[:3], ['import-checkpoint', '7', owner.current])
                owner.assertEqual(fields[4:6], [owner.archive.namespace, owner.selection['digest']])
                for name in FILES:
                    shutil.copyfile(owner.archive.root/owner.selection['digest']/name, owner.workspace/name)
                status = {'request_id': fields[3], 'workspace': owner.current,
                    'archive_namespace': owner.archive.namespace, 'generation': owner.selection['digest'],
                    'phase': 'ready', 'file_index': 3, 'native_result': 1}
                write_json(owner.data/'re2_coop_native_save_guard.json', {'checkpoint_import': status})
                catalog = {**status, 'schema': 1, 'at': int(time.time()), 'game_pid': 32,
                    'run_id': 'f'*32, 'guard_run_id': 'lua',
                    'reference': {'mode': 1, 'slot_id': 0, 'timestamp': '639001000000000000', 'scenario': 0}}
                write_json(owner.data/'re2_coop_checkpoint_catalog.json', catalog)
                return b'accepted import-checkpoint'

        self.pipe = Pipe()
        self.stop = Event()
        self.setup = CampaignSetup(self.data, self.pipe, self.stop)
        self.enterContext(patch('campaign_setup._steam_for_save'))
        self.enterContext(patch('campaign_setup.storage_guard_active', return_value=True))
        self.acl = self.enterContext(patch.object(CampaignSetup, '_ensure_live_guard'))
        self.enterContext(patch('checkpoint_workspace.storage_guard_active', return_value=True))
        self.enterContext(patch('readonly_save_control.read_active_guard', side_effect=lambda *a, **kw: deepcopy(self.guard)))
        self.enterContext(patch('readonly_save_control.read_connected_lobby', side_effect=lambda *a: (deepcopy(self.scope), deepcopy(self.lobby))))
        self.enterContext(patch('checkpoint_workspace.read_active_guard', side_effect=lambda *a, **kw: deepcopy(self.guard)))
        self.enterContext(patch('checkpoint_workspace.read_connected_lobby', side_effect=lambda *a: (deepcopy(self.scope), deepcopy(self.lobby))))
        self.runtime = self.enterContext(patch.object(self.pipe, 'prepare_new_game', wraps=self.pipe.prepare_new_game))

    def mount(self, data, pipe, profile, stop, *, namespace, revision, already_bound):
        self.mounts.append((namespace, already_bound))
        if self.mount_failure:
            raise self.mount_failure
        if not already_bound:
            self.current = namespace
        self.workspace = self.solo.parent/('coop-save-'+self.current)
        self.workspace.mkdir(exist_ok=True)
        self.guard.update(runtime_protection=True, campaign_mount_ready=self.current,
                          protection={'game_pid': 32, 'run_id': 'f'*32, 'campaign_namespace': self.current})
        if self.after_mount:
            self.after_mount()
        return object(), object()

    def prepare(self):
        return self.setup.enable_checkpoint(self.selection, 7)

    def test_reuses_selected_campaign_after_restart_and_preserves_solo_and_archive(self):
        for _ in range(2):
            result = self.prepare()
            self.assertEqual(result['selection'], self.selection)
            self.assertEqual(result['protection']['campaign_namespace'], self.archive.namespace)
            self.assertEqual(self.archive.verified(self.selection['digest']), self.manifest)
            self.assertEqual([p.name for p in self.solo.iterdir()], ['data00-1.bin'])
            self.assertEqual((self.solo/'data00-1.bin').read_bytes(), b'original system without scenario')
            self.assertFalse((self.data/'re2_coop_save_policy.json').exists())
            self.current = None  # Simulate a fresh native process with the same local working files.
            self.guard.pop('protection'); self.guard.pop('campaign_mount_ready')
            self.guard.pop('runtime_protection')
        self.assertEqual(self.mounts, [(self.archive.namespace, False)]*2)
        self.assertEqual(len(list(self.solo.parent.glob('coop-save-*'))), 1)
        self.assertEqual(self.revoked, [])

    def test_keeps_a_previously_bound_title_workspace(self):
        self.current = 'b'*32
        self.mount(self.data, self.pipe, None, self.stop, namespace=self.current, revision=7, already_bound=True)
        self.mounts.clear()
        before = set(self.solo.parent.iterdir())
        result = self.prepare()
        self.assertEqual(result['protection']['campaign_namespace'], 'b'*32)
        self.assertEqual(self.mounts, [])
        self.runtime.assert_not_called()
        self.assertEqual(set(self.solo.parent.iterdir()), before)
        self.assertEqual(self.revoked, [])

    def test_wrong_choice_world_or_cancel_never_begins_the_mount(self):
        for change in (lambda: self.lobby['settings']['coop_checkpoint'].update(difficulty=2),
                       lambda: self.guard.update(has_player=True),
                       lambda: self.guard.update(allowed_load_calls=False),
                       lambda: self.scope['membership'].update(revision=8), lambda: self.stop.set()):
            previous = deepcopy((self.lobby, self.guard, self.scope))
            change()
            with self.assertRaises(ValueError):
                self.prepare()
            self.lobby, self.guard, self.scope = previous
            self.stop.clear()
        self.runtime.assert_not_called()
        self.acl.assert_not_called()
        self.assertEqual(self.commands, [])

    def test_unavailable_old_workspace_never_allocates_a_random_fallback(self):
        self.mount_failure = ValueError('error exclusive coop save directory unavailable')
        with patch('campaign_setup.secrets.token_hex', side_effect=AssertionError('random fallback')):
            with self.assertRaisesRegex(ValueError, 'exclusive coop save directory'):
                self.prepare()
        self.assertEqual(self.mounts, [(self.archive.namespace, False)])
        self.assertEqual(self.revoked, [self.archive.namespace])
        self.assertEqual(self.commands, [])
        self.assertEqual(self.archive.verified(self.selection['digest']), self.manifest)

    def test_import_failure_does_not_revoke_an_existing_grant(self):
        self.current = 'b'*32
        self.mount(self.data, self.pipe, None, self.stop, namespace=self.current, revision=7, already_bound=True)
        with patch.object(self.pipe, 'request', side_effect=ValueError('native import failed')):
            with self.assertRaisesRegex(ValueError, 'native import failed'):
                self.prepare()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.revoked, [])

    def test_selection_loss_after_mount_revokes_only_the_new_grant(self):
        self.after_mount = lambda: self.lobby.update(revision=3)
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            self.prepare()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.revoked, [self.archive.namespace])
        self.assertEqual(self.archive.verified(self.selection['digest']), self.manifest)

    def test_guest_prepares_with_system_data_and_no_scenario_file(self):
        self.scope['role'] = 'G'
        result = self.prepare()
        self.assertEqual(result['scope']['role'], 'G')
        self.assertEqual(result['native_reference']['slot_id'], 0)
        self.assertEqual([p.name for p in self.solo.iterdir()], ['data00-1.bin'])
