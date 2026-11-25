import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from coop_checkpoint import FILES, HostArchive, serve_host
from load_witness import _read_json
from lobby_sync import write_json


class HostArchiveTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        solo = root / '123/883710/remote/win64_save'
        solo.mkdir(parents=True)
        self.solo = solo / 'data000.bin'
        self.solo.write_bytes(b'original')
        self.archive = HostArchive(solo, 'a' * 32)
        self.archive.source.mkdir()
        self.receipt = {'attempt': 'b' * 32, 'release': 'c' * 32, 'slot': 0, 'scenario': 0,
                        'difficulty': 1, 'timestamp': '639000000000000000'}

    def save(self, value):
        before = self.archive.before_save()
        for name in FILES:
            new = self.archive.source / (name + '.stmp')
            new.write_bytes(value + name.encode())
            new.replace(self.archive.source / name)
        return before

    def test_publish_retry_and_partial_second_generation(self):
        before = self.save(b'first')
        digest = self.archive.publish(before, self.receipt, lambda: None)
        self.assertEqual(self.archive.publish(before, self.receipt, lambda: None), digest)
        old = self.archive.verified(digest)
        before = self.archive.before_save()
        (self.archive.source / FILES[0]).write_bytes(b'partial autosave')
        with self.assertRaisesRegex(ValueError, 'Slotindex'):
            self.archive.publish(before, self.receipt, lambda: None)
        self.assertEqual(self.archive.verified(digest), old)
        self.assertEqual(list(self.archive.root.iterdir()), [self.archive.root / digest])
        self.assertEqual(self.solo.read_bytes(), b'original')

    def test_changed_source_or_lost_release_never_publishes(self):
        before = self.save(b'first')
        def disconnect():
            raise ValueError('release lost')
        with self.assertRaisesRegex(ValueError, 'release lost'):
            self.archive.publish(before, self.receipt, disconnect)
        with self.assertRaisesRegex(ValueError, 'geändert'):
            self.archive.publish(before, self.receipt, lambda: (self.archive.source / FILES[0]).write_bytes(b'next'))
        self.assertEqual(list(self.archive.root.iterdir()), [])

    def test_archive_corruption_and_unfinished_steam_write(self):
        before = self.save(b'first')
        staging = self.archive.source / (FILES[0] + '.stmp')
        staging.write_bytes(b'pending')
        with self.assertRaisesRegex(ValueError, 'Steam schreibt'):
            self.archive.publish(before, self.receipt, lambda: None)
        staging.unlink()
        digest = self.archive.publish(before, self.receipt, lambda: None)
        (self.archive.root / digest / FILES[0]).write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError, 'Archivierte'):
            self.archive.verified(digest)

    def test_restart_finds_last_intact_generation_without_a_solo_slot(self):
        solo = self.solo.parent
        self.solo.unlink()
        (solo / 'data00-1.bin').write_bytes(b'local user settings')
        first = self.archive.publish(self.save(b'first'), self.receipt, lambda: None)
        second = self.archive.publish(self.save(b'second'), {**self.receipt, 'timestamp': '639000000100000000'},
                                      lambda: None)
        import subprocess
        import sys
        from json import loads
        def restart():
            script = ('from coop_checkpoint import HostArchive; import json,sys; '
                      'print(json.dumps(HostArchive.recoverable(sys.argv[1])))')
            return loads(subprocess.check_output([sys.executable, '-B', '-c', script, str(solo)]))
        self.assertEqual([c['digest'] for c in restart()], [second, first])
        (self.archive.root / second / FILES[0]).write_bytes(b'damaged')
        (self.archive.root / '.pending-test').mkdir()
        self.assertEqual([c['digest'] for c in restart()], [first])
        self.assertEqual({f.name for f in solo.iterdir()}, {'data00-1.bin'})

    def test_host_button_waits_for_the_native_commit_before_publishing(self):
        data = self.archive.source.parent.parent / 'bridge'
        data.mkdir()
        scope = {'game_pid': 32, 'role': 'H', 'session_id': 'session', 'membership': {'revision': 5},
                 'guard_run_id': 'guard', 'attempt_id': self.receipt['attempt']}
        binding = {'game_pid': 32, 'run_id': 'run', 'campaign_namespace': self.archive.namespace}
        anchor = {'game_pid': 32, 'load_request_id': 'load', 'release_id': self.receipt['release'], 'snapshot_epoch': 'epoch'}
        campaign = {'game_pid': 32, 'role': 'H', 'session_id': 'session', 'revision': 5,
                    'attempt_id': scope['attempt_id'], 'protection_run_id': 'run', 'snapshot_epoch': 'epoch'}
        guard = {'protection': binding, 'campaign_mount_ready': self.archive.namespace, 'guard_run_id': 'guard',
                 'in_title': False, 'load_hold': {'phase': 'released', 'native_phase': 'released',
                    'release': {'id': anchor['release_id'], 'snapshot_epoch': 'epoch'},
                    'campaign': campaign, 'load_request_id': 'load'}}
        write_json(data / 're2_coop_checkpoint_button.json', {**anchor, 'at': int(time.time())})
        stop = Mock()
        stop.is_set.return_value = False
        path = data / 're2_coop_checkpoint_request.json'
        pending = self.archive.source / (FILES[0] + '.stmp')
        def tick(_):
            if path.exists():
                if 'host_checkpoint' in guard:
                    if pending.exists():
                        self.assertEqual(_read_json(data / 're2_coop_checkpoint_status.json')['phase'], 'saving')
                        self.assertFalse(self.archive.root.exists())
                        pending.unlink()
                        return False
                    return True
                self.save(b'native test double')
                pending.write_bytes(b'pending Steam commit')
                guard['host_checkpoint'] = {'id': _read_json(path)['id'], 'phase': 'complete',
                    **{k: self.receipt[k] for k in ('slot','scenario','difficulty','timestamp')}}
            return False
        stop.wait.side_effect = tick
        link = {k: scope[k] for k in ('game_pid','role','session_id','membership')}
        with (patch('readonly_save_control.read_active_guard', return_value=guard),
              patch('readonly_save_control.read_connected_lobby', return_value=(link, {})),
              patch('steam_pose_bridge.SteamPipe') as pipe):
            pipe.return_value.lobby_status.return_value = 'owned'
            pipe.return_value.membership_revision.return_value = 5
            pipe.return_value.cloud_status.return_value = 'cloud-app-disabled'
            serve_host(data, self.solo.parent, {'lobby_load': scope, 'protection': binding}, anchor, stop)
        report = _read_json(data / 're2_coop_checkpoint_status.json')
        self.assertEqual(report['phase'], 'saved')
        self.assertEqual(self.archive.verified(report['digest'])['timestamp'], self.receipt['timestamp'])

    def test_unfinished_native_commit_expires_and_preserves_the_previous_generation(self):
        digest = self.archive.publish(self.save(b'confirmed'), self.receipt, lambda: None)
        previous = self.archive.verified(digest)
        data = self.archive.source.parent.parent / 'bridge'
        data.mkdir()
        scope = {'game_pid': 32, 'role': 'H', 'session_id': 'session', 'membership': {'revision': 5},
                 'guard_run_id': 'guard', 'attempt_id': self.receipt['attempt']}
        binding = {'game_pid': 32, 'run_id': 'run', 'campaign_namespace': self.archive.namespace}
        anchor = {'game_pid': 32, 'load_request_id': 'load', 'release_id': self.receipt['release'],
                  'snapshot_epoch': 'epoch'}
        campaign = {'game_pid': 32, 'role': 'H', 'session_id': 'session', 'revision': 5,
                    'attempt_id': scope['attempt_id'], 'protection_run_id': 'run', 'snapshot_epoch': 'epoch'}
        guard = {'protection': binding, 'campaign_mount_ready': self.archive.namespace, 'guard_run_id': 'guard',
                 'in_title': False, 'load_hold': {'phase': 'released', 'native_phase': 'released',
                    'release': {'id': anchor['release_id'], 'snapshot_epoch': 'epoch'},
                    'campaign': campaign, 'load_request_id': 'load'}}
        write_json(data / 're2_coop_checkpoint_button.json', {**anchor, 'at': int(time.time())})
        stop = Mock()
        stop.is_set.return_value = False
        path = data / 're2_coop_checkpoint_request.json'
        status = data / 're2_coop_checkpoint_status.json'
        def tick(_):
            if status.exists() and _read_json(status)['phase'] == 'failed':
                return True
            if path.exists() and 'host_checkpoint' not in guard:
                self.save(b'unfinished')
                (self.archive.source / (FILES[0] + '.stmp')).write_bytes(b'pending')
                guard['host_checkpoint'] = {'id': _read_json(path)['id'], 'phase': 'complete',
                    **{k: self.receipt[k] for k in ('slot', 'scenario', 'difficulty', 'timestamp')}}
            return False
        stop.wait.side_effect = tick
        link = {k: scope[k] for k in ('game_pid', 'role', 'session_id', 'membership')}
        with (patch('readonly_save_control.read_active_guard', return_value=guard),
              patch('readonly_save_control.read_connected_lobby', return_value=(link, {})),
              patch('steam_pose_bridge.SteamPipe') as pipe,
              patch('coop_checkpoint.time.monotonic', side_effect=[0, 34])):
            pipe.return_value.lobby_status.return_value = 'owned'
            pipe.return_value.membership_revision.return_value = 5
            pipe.return_value.cloud_status.return_value = 'cloud-app-disabled'
            serve_host(data, self.solo.parent, {'lobby_load': scope, 'protection': binding}, anchor, stop)
        self.assertIn('Zeitüberschreitung', _read_json(status)['reason'])
        self.assertEqual(self.archive.verified(digest), previous)
        self.assertEqual(list(self.archive.root.iterdir()), [self.archive.root / digest])
