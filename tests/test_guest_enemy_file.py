from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from enemy_live import unavailable_view
from guest_enemy_file import GuestEnemyFile
from steam_pose_bridge import SteamPipe
import steam_snapshot_transfer as transfer
from tests.test_enemy_witness import guid, report
from tests.test_steam_enemy_live import enemy, observation


class GuestEnemyFileTests(unittest.TestCase):
    def test_initialization_renewal_and_disconnect_are_local_and_ordered(self):
        source = report()
        checkpoint = source['state']['checkpoint']
        feed = SimpleNamespace(reader=SimpleNamespace(accepted=source), checkpoint=checkpoint,
                               request_id='d' * 32, reference={'slot_id': 4})
        view = observation(200, {guid(1): enemy()})
        with TemporaryDirectory() as directory, patch('guest_enemy_file.time.time', return_value=100) as clock:
            path = Path(directory) / GuestEnemyFile.filename
            path.write_text('previous live receipt', encoding='utf-8')
            output = GuestEnemyFile(directory, 'a' * 32)
            first = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual((first['sequence'], first['view']['available'], first['load']), (1, False, None))
            output.publish(view, feed)
            received = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(received['view'], view)
            self.assertEqual(received['load']['checkpoint'], checkpoint)
            self.assertEqual(received['load']['observer_sequence'], source['sequence'])
            clock.return_value = 101
            output.publish(view, feed)
            renewed = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual((renewed['sequence'], renewed['received_at'], renewed['generation']), (3, 101, 100000000))
            output.publish(unavailable_view('stream_interrupted'))
            cleared = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(cleared['sequence'], 4)
            self.assertEqual(cleared['view']['enemies'], {})
            self.assertIsNone(cleared['load'])
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_stale_local_report_cannot_be_renewed_by_a_peer(self):
        source = report()
        feed = SimpleNamespace(reader=SimpleNamespace(accepted=source), checkpoint=source['state']['checkpoint'],
                               request_id='d' * 32, reference={'slot_id': 4})
        with TemporaryDirectory() as directory, patch('guest_enemy_file.time.time', return_value=104):
            output = GuestEnemyFile(directory, 'a' * 32)
            output.publish(observation(200, {guid(1): enemy(7)}), feed)
            result = json.loads(output.path.read_text(encoding='utf-8'))
            self.assertEqual(result['view'], unavailable_view('local_source_unavailable'))
            self.assertIsNone(result['load'])

    def test_cli_clears_an_old_export_before_a_failed_bootstrap(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / GuestEnemyFile.filename
            path.write_text('old live receipt', encoding='utf-8')
            pipe = SteamPipe(123)
            pipe.request = Mock(side_effect=OSError('no Steam peer'))
            command = ['steam_snapshot_transfer.py', '--role', 'guest', '--pid', '123', '--data', directory,
                       '--file', str(Path(directory) / 'initial-snapshot.json'), '--native-enemies',
                       '--load-request-id', 'c' * 32, '--save-slot', 'scenario:4', '--allow-save-date', '2026-11-11',
                       '--session-id', 'a' * 32, '--request-id', 'd' * 32, '--live-updates', '2', '--export-live-enemies']
            with (patch.object(transfer, 'SteamPipe', return_value=pipe), patch.object(sys, 'argv', command),
                  patch.object(sys, 'platform', 'win32'), redirect_stderr(io.StringIO())):
                self.assertEqual(transfer.main(), 1)
            result = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(result['view'], unavailable_view('starting'))
            self.assertEqual(result['session_id'], 'a' * 32)
            self.assertIsNone(result['load'])
            self.assertFalse((Path(directory) / 'initial-snapshot.json').exists())


if __name__ == '__main__':
    unittest.main()
