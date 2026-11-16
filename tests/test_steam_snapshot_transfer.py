from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
from queue import Empty, Queue
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from protocol.snapshot_transfer import MAX_PACKET_BYTES, snapshot_packets
from steam_pose_bridge import SteamPipe
import steam_snapshot_transfer as transfer
from sync_model import Host


SESSION = 'a' * 32
REQUEST = 'b' * 32
EPOCH = b'epoch-01'


class NativePipePair:
    """Model the native read/send envelope and its bounded incoming queue."""

    def __init__(self):
        self.to_guest = Queue(maxsize=32)
        self.to_host = Queue(maxsize=32)
        self.sent_by_host = []
        self.peak_guest_pending = 0

    def pipe(self, role):
        incoming, outgoing = ((self.to_guest, self.to_host) if role == b'G'
                              else (self.to_host, self.to_guest))
        pipe = SteamPipe(123)

        def request(data):
            if data == b'R':
                try:
                    payload = incoming.get_nowait()
                except Empty:
                    payload = b''
                return role + EPOCH + payload
            if data[:9] != b'S' + EPOCH:
                return b'E'
            payload = data[9:]
            outgoing.put_nowait(payload)
            if role == b'H':
                self.sent_by_host.append(payload)
                self.peak_guest_pending = max(self.peak_guest_pending, outgoing.qsize())
            return b'S'

        pipe.request = request
        return pipe


class SteamSnapshotTransferTests(unittest.TestCase):
    def test_pulls_nearly_one_mib_through_bounded_pipe(self):
        host = Host(SESSION)
        host.emit('enemy', 'test-enemy', {'observation': 'ä' * 510000})
        snapshot = host.snapshot()
        pair = NativePipePair()
        pair.to_guest.put_nowait(b'{"type":"unrelated-pose"}')
        # The first pull from a previous attempt must be ignored.
        pair.to_host.put_nowait(bytes.fromhex('52325001' + SESSION + 'c' * 32 + '00000000'))
        with patch.object(transfer, 'TIMEOUT', 4), ThreadPoolExecutor(max_workers=2) as executor:
            serve = executor.submit(transfer.transfer, pair.pipe(b'H'), b'H', SESSION, REQUEST,
                                    snapshot=snapshot)
            download = executor.submit(transfer.transfer, pair.pipe(b'G'), b'G', SESSION, REQUEST)
            self.assertEqual(download.result(), snapshot)
            self.assertEqual(serve.result(), snapshot)
        self.assertEqual(pair.sent_by_host, list(snapshot_packets(snapshot, REQUEST)))
        self.assertGreater(len(pair.sent_by_host), 250)
        self.assertLessEqual(pair.peak_guest_pending, transfer.WINDOW)
        self.assertLessEqual(max(map(len, pair.sent_by_host)), MAX_PACKET_BYTES)

    def test_changed_epoch_aborts_guest_before_accepting_snapshot(self):
        pipe = SteamPipe(123)
        snapshot = Host(SESSION).snapshot()
        packet = snapshot_packets(snapshot, REQUEST)[0]
        pipe.request = Mock(side_effect=[b'G' + EPOCH, b'S', b'Gepoch-02' + packet])
        with self.assertRaisesRegex(OSError, 'peer changed'):
            transfer.transfer(pipe, b'G', SESSION, REQUEST)
        self.assertEqual(pipe.request.call_count, 3)

    def test_cli_keeps_previous_guest_file_when_transfer_digest_fails(self):
        pipe = SteamPipe(123)
        packet = snapshot_packets(Host(SESSION).snapshot(), REQUEST)[0]
        pipe.request = Mock(side_effect=[b'G' + EPOCH, b'S', b'G' + EPOCH + packet[:-1] + b'x'])
        with TemporaryDirectory() as directory:
            data = Path(directory)
            output = data / 'guest.json'
            output.write_bytes(b'prior result')
            command = ['steam_snapshot_transfer.py', '--role', 'guest', '--pid', '123',
                       '--data', directory, '--file', str(output),
                       '--session-id', SESSION, '--request-id', REQUEST]
            errors = io.StringIO()
            with (patch.object(transfer, 'SteamPipe', return_value=pipe),
                  patch.object(sys, 'argv', command), patch.object(sys, 'platform', 'win32'),
                  redirect_stderr(errors)):
                self.assertEqual(transfer.main(), 1)
            self.assertIn('transfer digest mismatch', errors.getvalue())
            self.assertEqual(output.read_bytes(), b'prior result')
            self.assertEqual(pipe.request.call_count, 3)

    def test_guest_file_replaces_previous_result_only_with_a_verified_snapshot(self):
        pipe = SteamPipe(123)
        snapshot = Host(SESSION).snapshot()
        packet = snapshot_packets(snapshot, REQUEST)[0]
        pipe.request = Mock(side_effect=[b'G' + EPOCH, b'S', b'G' + EPOCH + packet, b'S'])
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'guest.json'
            output.write_bytes(b'prior result')
            command = ['steam_snapshot_transfer.py', '--role', 'guest', '--pid', '123',
                       '--data', directory, '--file', str(output),
                       '--session-id', SESSION, '--request-id', REQUEST]
            with (patch.object(transfer, 'SteamPipe', return_value=pipe),
                  patch.object(sys, 'argv', command), patch.object(sys, 'platform', 'win32'),
                  redirect_stdout(io.StringIO())):
                self.assertEqual(transfer.main(), 0)
            self.assertEqual(transfer._read_snapshot(output), snapshot)
            self.assertEqual({file.name for file in Path(directory).iterdir()},
                             {output.name, 're2_coop_pose_bridge.lock'})
            self.assertEqual(pipe.request.call_args.args[0][-4:], b'\xff' * 4)


if __name__ == '__main__':
    unittest.main()
