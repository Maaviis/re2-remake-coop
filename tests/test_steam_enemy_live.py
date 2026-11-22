from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest
from unittest.mock import Mock, patch

from enemy_live import FLAG, SCOPE, EnemyLiveFeed, unavailable_view, validate_live_view
from protocol import v1
from steam_pose_bridge import SteamPipe
import steam_snapshot_transfer as transfer
from tests.test_enemy_witness import guid, report
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

    def test_campaign_publishes_only_matching_area_and_identity(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        area = {'scenario': 0, 'map': 3, 'area': 5}
        view = {**observation(10, {guid(1): enemy(37), guid(2): enemy(19)}), 'campaign_area': area}
        local = {**observation(8, {guid(1): enemy(70), guid(2): enemy(70, 2)}), 'campaign_area': area}
        other_area = {**local, 'campaign_area': {**area, 'area': 4}}
        host_feed = Feed(view, None, None)
        guest_feed = Feed(other_area, local, other_area)
        deliveries = []

        def publish(sample, _feed=None):
            deliveries.append(sample)

        options = {'campaign': True, 'expected_epoch': EPOCH}
        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 3), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST, host_feed, 3, **options)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, guest_feed, 3, publish=publish, **options)
            serving.result()
        self.assertEqual(deliveries, [
            unavailable_view('campaign_area_mismatch'),
            {**view, 'enemies': {guid(1): enemy(37)}},
            unavailable_view('campaign_area_mismatch'),
            unavailable_view('stopped'),
        ])

    def test_campaign_recovers_when_guest_cannot_acknowledge_a_snapshot(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        original_request = guest.request
        ack_lost = False

        def request(data):
            nonlocal ack_lost
            if data[9:13] == transfer._PULL and data[-4:] == b'\xff' * 4 and not ack_lost:
                ack_lost = True
                raise TimeoutError('synthetic pipe timeout')
            return original_request(data)

        guest.request = request
        view = {**observation(11, {guid(1): enemy(37)}),
                'campaign_area': {'scenario': 1, 'map': 3, 'area': 4}}
        output = []
        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 0.5), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST,
                                  Feed(view, None), 2, campaign=True)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, Feed(view), 2,
                                       emit=output.append, campaign=True)
            serving.result()
        self.assertTrue(ack_lost)
        self.assertEqual(output, [unavailable_view('stream_interrupted'), view, unavailable_view('stopped')])

    def test_changed_epoch_between_snapshots_immediately_clears_live_output(self):
        guest = SteamPipe(123)
        guest.epoch = EPOCH
        guest.request = Mock(return_value=b'Gepoch-02')
        output = []
        with self.assertRaisesRegex(OSError, 'peer changed'):
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, Feed(), 1, emit=output.append)
        self.assertEqual(output, [unavailable_view('stream_interrupted')])
        guest.request.assert_called_once_with(b'R')

    def test_opt_in_carries_a_death_observed_between_guest_pulls(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        host_feed = EnemyLiveFeed('.', REQUEST, {}, death_evidence=True)
        first_pull, controller_removed = Event(), Event()
        native_death_observed = False

        def native_sample(*_args, **_kwargs):
            nonlocal native_death_observed
            state = report()['state']
            sequence = 9
            if first_pull.is_set():
                state['active_count'] = 0
                if native_death_observed:
                    sequence = 11
                    state['entries'][0]['live'] = {'present': False}
                    controller_removed.set()
                else:
                    sequence = 10
                    state['entries'][0]['live'].update(active=False, hp=0, is_dead=True)
                    native_death_observed = True
            return {'observer_sequence': sequence, 'observed_at': 100, 'state': state}

        host_feed.reader.for_load = native_sample
        guest_feed = Feed(observation(1, {guid(1): enemy(hp=7)}), None, None)
        output = []

        def emit(view):
            output.append(view)
            if len(output) == 1:
                first_pull.set()
                self.assertTrue(controller_removed.wait(3), 'host did not sample between pulls')

        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 4), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST, host_feed, 3,
                                  death_evidence=True)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, guest_feed, 3, emit=emit,
                                       death_evidence=True)
            serving.result()

        self.assertEqual(output[0]['death_observations'], {})
        self.assertEqual(output[1]['enemies'], {})
        self.assertEqual(output[1]['death_observations'][guid(1)],
                         {'kind_id': 4, 'inherit_id': -1, 'hp': 0, 'active': False, 'is_dead': True,
                          'observer_sequence': 10, 'observed_at': 100})
        self.assertEqual(output[2:], [unavailable_view('stopped')])

    def test_rejects_malformed_live_view_and_unavailable_with_enemy_values(self):
        view = observation(10, {guid(1): enemy(hp=True)})
        with self.assertRaises(ValueError):
            validate_live_view(view)
        view = {**unavailable_view('source_unavailable'), 'enemies': {guid(1): enemy()}}
        with self.assertRaises(ValueError):
            validate_live_view(view)

    def test_death_observation_requires_explicit_flag_and_consistent_identity(self):
        death = {'kind_id': 4, 'inherit_id': -1, 'hp': 0, 'active': False, 'is_dead': True,
                 'observer_sequence': 9, 'observed_at': 99}
        view = {**observation(10, {}), 'death_observations': {guid(1): death}}
        validate_live_view(view)
        for change in ({'is_dead': False}, {'observer_sequence': 11}, {'observed_at': 101}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_live_view({**view, 'death_observations': {guid(1): {**death, **change}}})
        with self.assertRaises(ValueError):
            validate_live_view({**view, 'enemies': {guid(1): enemy()}})

    def test_unavailable_local_guard_clears_previously_matched_enemy(self):
        pair = NativePipePair()
        host, guest = pair.pipe(b'H'), pair.pipe(b'G')
        host.epoch = guest.epoch = EPOCH
        original = observation(10, {guid(1): enemy()})
        host_feed = Feed(original, None, None)
        guest_feed = Feed(original, None, unavailable_view('source_unavailable'))
        output, deliveries = [], []
        with (patch.object(transfer, 'LIVE_INTERVAL', 0),
              patch.object(transfer, 'LIVE_TIMEOUT', 3), ThreadPoolExecutor(max_workers=2) as pool):
            serving = pool.submit(transfer.follow_enemy_live, host, b'H', SESSION, REQUEST, host_feed, 3)
            transfer.follow_enemy_live(guest, b'G', SESSION, REQUEST, guest_feed, 3, emit=output.append,
                                       publish=lambda view, feed=None: deliveries.append(view))
            serving.result()
        self.assertEqual(output, [original, unavailable_view('local_source_unavailable'), unavailable_view('stopped')])
        self.assertEqual(deliveries, [original, *output])


if __name__ == '__main__':
    unittest.main()
