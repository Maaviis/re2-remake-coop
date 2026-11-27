import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from coop_diagnostics import SessionDiagnostics
from protocol import v1
from steam_pose_bridge import SteamPipe


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.scope = ('a' * 32, 'b' * 32)
        self.host, self.guest = [SessionDiagnostics(root / role / 'reframework/data', 12, role, 'd' * 40)
                                 for role in ('H', 'G')]
        self.pipe = Mock()
        for side in (self.host, self.guest):
            side.data.mkdir(parents=True)
            side.engine.write_text('old session\n')
            side.bind(self.scope)

    def read_host(self):
        return [json.loads(s) for s in self.host.path.read_text(encoding='utf-8').splitlines()]

    def test_real_log_lines_retry_ack_and_scope(self):
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        with self.guest.engine.open('a') as log:
            for entry in ('[info] RE2_COOP_CUTSCENE menu evt_10001/1/1/accept',
                          '[info] RE2_COOP_SAVE_GUARD prepare=hooks_queued',
                          '[info] RE2_COOP_SAVE_GUARD prepare=C:/Users/secret-name/steam',
                          '[warning] [Plugin] RE2_COOP_NATIVE_SAVE_GUARD campaign_lost=campaign_binding_cleared',
                          '[error] RE2_COOP_GUEST_EQUIPMENT C:/Users/secret-name/steam',
                          '[info] other mod with secret-name'):
                print(f'[{stamp}] [REFramework] {entry}', file=log)
        self.guest.tick(self.pipe, self.scope, {}, None, 1)
        packet = self.pipe.send.call_args.args[0]
        self.assertEqual(v1.decode(v1.encode(packet, steam_pose=True), steam_pose=True), packet)
        self.assertNotIn('secret-name', str(packet))
        self.host.tick(self.pipe, self.scope, {}, {**packet, 'request_id': 'c' * 32}, 1)
        self.assertFalse(any(row['role'] == 'Gast' for row in self.read_host()))
        self.host.tick(self.pipe, self.scope, {}, packet, 2)
        # Lost acknowledgment replays exactly this batch; the host writes it only once.
        self.guest.tick(self.pipe, self.scope, {}, None, 4)
        self.assertEqual(self.pipe.send.call_args.args[0], packet)
        self.host.tick(self.pipe, self.scope, {}, packet, 4)
        ack = self.pipe.send.call_args.args[0]
        self.guest.tick(self.pipe, self.scope, {}, ack, 4.1)
        self.assertIsNone(self.guest.flight)
        lines = self.read_host()
        self.assertEqual(sum('menu evt_10001' in r['detail'] and r['role'] == 'Gast' for r in lines), 1)
        self.assertTrue(any('campaign_binding_cleared' in r['detail'] for r in lines))
        self.assertTrue(any(r['role'] == 'Gast' and r['detail'] == 'info prepare=hooks_queued' for r in lines))
        self.assertTrue(any(r['role'] == 'Host' for r in lines))
        self.guest.note('ERROR', 'previous guest error')
        self.guest.tick(self.pipe, ('c' * 32, '3' * 32), {}, None, 5)
        self.assertNotIn('previous guest error', str(self.pipe.send.call_args.args[0]))
        self.assertFalse((self.guest.data/'re2_coop_logs').exists())

    def test_private_exception_and_failed_write(self):
        try:
            raise OSError(2, 'private path /secret-name')
        except OSError as exc:
            self.guest.error(exc)
        self.guest.tick(self.pipe, self.scope, {}, None, 1)
        packet = self.pipe.send.call_args.args[0]
        self.assertIn('system_code=2', str(packet))
        self.assertNotIn('secret-name', str(packet))
        self.pipe.reset_mock()
        with patch.object(self.host, '_write', side_effect=PermissionError):
            self.host.tick(self.pipe, self.scope, {}, packet, 1)
        self.pipe.send.assert_not_called()
        self.host.tick(self.pipe, self.scope, {}, packet, 2)
        self.assertEqual(self.pipe.send.call_args.args[0]['type'], 'coop_log_ack')
        for bad in ([[1, 'ERR', 'two\nlines']], [[1, 'ERR', 'x' * 221]], packet['records'] * 10):
            with self.assertRaises(v1.ProtocolError):
                v1.encode({**packet, 'records': bad}, steam_pose=True)

    def test_diagnostic_send_error_preserves_buffered_gameplay(self):
        pipe = SteamPipe(42)
        pipe.epoch = b'epoch001'
        pipe._pending_poses.append(b'queued')
        with patch.object(pipe, 'request', side_effect=TimeoutError), self.assertRaises(TimeoutError):
            pipe.send(dict(version=1, type='coop_log_ack', session_id=self.scope[0], request_id=self.scope[1], batch=1))
        self.assertEqual(pipe.receive(), b'queued')
