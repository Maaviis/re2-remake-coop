from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

from enemy_live import FLAG, SCOPE, unavailable_view, validate_live_view
from protocol import v1
from steam_pose_bridge import SteamPipe
import steam_snapshot_transfer as transfer
from tests.test_enemy_witness import guid
from tests.test_steam_snapshot_transfer import EPOCH, NativePipePair, REQUEST, SESSION


def enemy(hp=0, inherit_id=-1):
    return {'kind_id': 4, 'inherit_id': inherit_id, 'hp': hp, 'default_hp': 100,
            'is_live': True, 'is_dead': False}


def observation(sequence, enemies):
    return {'schema': 1, 'scope': SCOPE, 'available': True, 'reason': 'ok',
            'continuous': False, 'observer_sequence': sequence, 'observed_at': 100, 'enemies': enemies}


class Feed:
    def __init__(self, *observations):
        self.observations = iter(observations)
        self.latest = None

    def poll(self):
        view = next(self.observations)
        if view is not None:
            self.latest = view


class SteamEnemyLiveTests(unittest.TestCase):
    def test_multichunk_live_view_heartbeat_and_source_loss(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        host_rows = {guid(i): enemy() for i in range(1, 81)}
        host_feed = Feed(observation(10, host_rows), observation(13, host_rows),
                         unavailable_view('source_unavailable'))
        guest_feed = Feed(observation(6, {guid(1): enemy(30), guid(2): enemy(inherit_id=2)}),
                          observation(7, {}), None)
        output = []
        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 3), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST, host_feed, 3)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, guest_feed, 3, emit=output.append)
            serving.result()

        self.assertEqual(output[0]['enemies'], {guid(1): enemy()})
        self.assertEqual(output[0]['enemies'][guid(1)]['hp'], 0)
        self.assertFalse(output[0]['enemies'][guid(1)]['is_dead'])
        self.assertTrue(output[1]['available'])
        self.assertEqual(output[1]['enemies'], {})
        self.assertEqual(output[2:], [unavailable_view('source_unavailable'), unavailable_view('stopped')])
        frames = {}
        for packet in pair.sent_by_host:
            frames.setdefault(int.from_bytes(packet[36:44], 'big'), []).append(packet)
        self.assertGreater(len(frames[1]), 1)
        self.assertEqual(len(frames[2]), 1)
        self.assertIsNone(v1.decode(frames[2][0][84:])['data']['state']['flags'][FLAG])
        self.assertLessEqual(pair.peak_guest_pending, transfer.WINDOW)

    def test_changed_epoch_between_snapshots_immediately_clears_live_output(self):
        guest = SteamPipe(123)
        guest.epoch = EPOCH
        guest.request = Mock(return_value=b'Gepoch-02')
        output = []
        with self.assertRaisesRegex(OSError, 'peer changed'):
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, Feed(), 1, emit=output.append)
        self.assertEqual(output, [unavailable_view('stream_interrupted')])
        guest.request.assert_called_once_with(b'R')

    def test_rejects_malformed_live_view_and_unavailable_with_enemy_values(self):
        view = observation(10, {guid(1): enemy(hp=True)})
        with self.assertRaises(ValueError):
            validate_live_view(view)
        view = {**unavailable_view('source_unavailable'), 'enemies': {guid(1): enemy()}}
        with self.assertRaises(ValueError):
            validate_live_view(view)

    def test_unavailable_local_guard_clears_previously_matched_enemy(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        original = observation(10, {guid(1): enemy()})
        host_feed = Feed(original, None)
        guest_feed = Feed(original, unavailable_view('source_unavailable'))
        output = []
        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 3), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST, host_feed, 2)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, guest_feed, 2, emit=output.append)
            serving.result()
        self.assertEqual(output, [original, unavailable_view('local_source_unavailable'), unavailable_view('stopped')])


if __name__ == '__main__':
    unittest.main()
