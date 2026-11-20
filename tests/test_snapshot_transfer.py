from copy import deepcopy
import unittest

from protocol import v1
from protocol.snapshot_transfer import (
    MAX_PACKET_BYTES, MAX_SNAPSHOT_BYTES, TRANSFER_TIMEOUT, SnapshotReceiver, snapshot_packets,
)
from steam_pose_bridge import MAX_PAYLOAD
from sync_model import Host, Replica, state_digest


SESSION = 'a' * 32
REQUEST = 'b' * 32


class SnapshotTransferTests(unittest.TestCase):
    def setUp(self):
        self.replica = Replica()
        self.host = Host(SESSION)
        self.host.emit('enemy', 'test-enemy', {'hp': 27, 'observation': 'ä' * 60000})
        self.snapshot = self.host.snapshot()
        self.packets = snapshot_packets(self.snapshot, REQUEST)
        self.now = 10
        self.receiver = SnapshotReceiver(self.replica, SESSION, REQUEST, clock=lambda: self.now)

    def test_large_snapshot_commits_once_with_reordering_and_duplicates(self):
        self.assertEqual(MAX_PACKET_BYTES, MAX_PAYLOAD)
        self.assertGreater(len(self.packets), 25)
        self.assertEqual(max(map(len, self.packets)), MAX_PAYLOAD)
        self.assertEqual(self.packets[0][:44].hex(), '52325301' + SESSION + REQUEST + '0000000000000001')
        before = self.replica.snapshot()
        for packet in reversed(self.packets[1:]):
            self.assertFalse(self.receiver.receive(packet))
            self.assertFalse(self.receiver.receive(packet))
        self.assertEqual(self.replica.snapshot(), before)
        self.assertTrue(self.receiver.receive(self.packets[0]))
        self.assertEqual(self.replica.snapshot(), self.snapshot)
        self.assertFalse(self.receiver.receive(self.packets[0]))

    def test_short_snapshot_uses_one_packet(self):
        host = Host(SESSION)
        packets = snapshot_packets(host.snapshot(), REQUEST)
        self.assertEqual(len(packets), 1)
        self.assertTrue(self.receiver.receive(packets[0]))
        self.assertEqual(self.replica.snapshot(), host.snapshot())

    def test_missing_chunk_expires_without_touching_replica(self):
        before = self.replica.snapshot()
        self.receiver.receive(self.packets[0])
        self.now += TRANSFER_TIMEOUT - 1
        for packet in self.packets[2:]:
            self.assertFalse(self.receiver.receive(packet))
        self.now += 1
        self.assertTrue(self.receiver.expire())
        self.assertFalse(self.receiver.receive(self.packets[1]))
        self.assertEqual(self.replica.snapshot(), before)

    def test_foreign_session_request_and_bad_bounds_do_not_replace_pending_data(self):
        self.receiver.receive(self.packets[0])
        foreign = Host('c' * 32)
        oversized = self.packets[0][:44] + (MAX_SNAPSHOT_BYTES + 1).to_bytes(4, 'big') + self.packets[0][48:]
        for packet in (
            snapshot_packets(foreign.snapshot(), REQUEST)[0],
            snapshot_packets(self.snapshot, 'd' * 32)[0],
            oversized,
            self.packets[1][:-1],
            self.packets[1] + b'x',
        ):
            with self.assertRaises(v1.ProtocolError):
                self.receiver.receive(packet)
        for packet in self.packets[1:-1]:
            self.assertFalse(self.receiver.receive(packet))
        self.assertTrue(self.receiver.receive(self.packets[-1]))

    def test_conflicting_duplicate_cancels_transfer(self):
        self.receiver.receive(self.packets[0])
        with self.assertRaisesRegex(v1.ProtocolError, 'conflicting'):
            self.receiver.receive(self.packets[0][:-1] + b'!')
        self.assertFalse(self.receiver.receive(self.packets[-1]))
        self.assertIsNone(self.replica.session_id)

    def test_corrupted_transfer_is_rejected_at_completion(self):
        self.receiver.receive(self.packets[0][:-1] + b'!')
        for packet in self.packets[1:-1]:
            self.assertFalse(self.receiver.receive(packet))
        with self.assertRaisesRegex(v1.ProtocolError, 'transfer digest mismatch'):
            self.receiver.receive(self.packets[-1])
        self.assertIsNone(self.replica.session_id)

    def test_valid_transfer_digest_does_not_replace_state_digest_check(self):
        snapshot = {**self.snapshot, 'digest': '0' * 64}
        packets = snapshot_packets(snapshot, REQUEST)
        for packet in packets[:-1]:
            self.receiver.receive(packet)
        with self.assertRaisesRegex(v1.ProtocolError, 'snapshot digest mismatch'):
            self.receiver.receive(packets[-1])
        self.assertIsNone(self.replica.session_id)

    def test_snapshot_cannot_override_newer_or_different_current_sequence(self):
        for newer in (False, True):
            snapshot = deepcopy(self.snapshot)
            snapshot['sequence'] += int(newer)
            snapshot['state']['enemies']['test-enemy']['hp'] = 6
            snapshot['digest'] = state_digest(snapshot['state'])
            self.replica.restore(snapshot)
            receiver = SnapshotReceiver(self.replica, SESSION, REQUEST)
            for packet in self.packets[:-1]:
                receiver.receive(packet)
            with self.assertRaisesRegex(v1.ProtocolError, 'current authoritative sequence|stale snapshot'):
                receiver.receive(self.packets[-1])
            self.assertEqual(self.replica.snapshot(), snapshot)

    def test_snapshot_sequence_must_match_packet_header(self):
        packet = snapshot_packets(Host(SESSION).snapshot(), REQUEST)[0]
        packet = packet[:43] + b'\x01' + packet[44:]
        with self.assertRaisesRegex(v1.ProtocolError, 'packet headers'):
            self.receiver.receive(packet)
        self.assertIsNone(self.replica.session_id)

    def test_failed_state_copy_keeps_previous_replica_sequence(self):
        observation = 'value'
        for _ in range(600):
            observation = [observation]
        self.snapshot['state']['enemies']['nested'] = observation
        self.snapshot['digest'] = state_digest(self.snapshot['state'])
        before = self.replica.snapshot()
        packets = snapshot_packets(self.snapshot, REQUEST)
        for packet in packets[:-1]:
            self.assertFalse(self.receiver.receive(packet))
        with self.assertRaisesRegex(v1.ProtocolError, 'recursion'):
            self.receiver.receive(packets[-1])
        self.assertEqual(self.replica.snapshot(), before)

    def test_cancelled_transfer_cannot_resume(self):
        self.receiver.receive(self.packets[0])
        self.receiver.close()
        for packet in self.packets[1:]:
            self.assertFalse(self.receiver.receive(packet))
        self.assertIsNone(self.replica.session_id)

    def test_sender_rejects_oversized_snapshots(self):
        self.host.emit('enemy', 'oversized', {'observation': 'x' * MAX_SNAPSHOT_BYTES})
        with self.assertRaisesRegex(v1.ProtocolError, 'byte limit'):
            snapshot_packets(self.host.snapshot(), REQUEST)


if __name__ == '__main__':
    unittest.main()
