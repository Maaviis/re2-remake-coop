import socket
from threading import Thread
import unittest

from enemy_live import FLAG, EnemyLiveFeed
from protocol import v1
from tests import test_enemy_witness as witness
from tests.test_load_witness import sample
from wire import Server, join_replica, receive, send


class EnemyLiveTests(unittest.TestCase):
    def setUp(self):
        fixture = witness.EnemyWitnessTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.feed = EnemyLiveFeed(fixture.data, fixture.request, fixture.reference)

    def sample(self, sequence, *, hp=7, dead=False, active=True, present=True, at=100):
        report = witness.report()
        report.update(sequence=sequence, observed_at=at)
        state = report['state']
        if present:
            state['entries'][0]['live'].update(active=active, hp=hp, is_dead=dead)
        else:
            state['entries'][0]['live'] = {'present': False}
        state['active_count'] = int(active and present)
        self.fixture.write(report, core={**sample(), 'sequence': sequence, 'observed_at': at},
                           guard={**self.fixture.guard, 'at': at})
        return self.feed.poll(now=at)

    def test_unchanged_samples_do_not_publish_and_hp_and_death_remain_independent(self):
        enemy = witness.guid(1)
        baseline = self.feed.poll(now=100)
        self.assertFalse(baseline['continuous'])
        self.assertEqual(set(baseline['enemies']), {enemy})
        self.assertIsNone(self.sample(10))
        self.assertIsNone(self.feed.poll(now=100))
        changed = self.sample(11, hp=0)
        self.assertTrue(changed['continuous'])
        self.assertEqual(changed['observer_sequence'], 11)
        self.assertEqual(changed['enemies'][enemy]['hp'], 0)
        self.assertFalse(changed['enemies'][enemy]['is_dead'])
        death_flag = self.sample(12, hp=0, dead=True)
        self.assertTrue(death_flag['enemies'][enemy]['is_dead'])
        absent = self.sample(13, hp=0, dead=True, active=False)
        self.assertTrue(absent['available'])
        self.assertEqual(absent['enemies'], {})
        self.assertNotIn('death_observations', absent)

    def test_inactive_native_death_survives_controller_removal_and_expires(self):
        fixture = self.fixture
        self.feed = EnemyLiveFeed(fixture.data, fixture.request, fixture.reference, death_evidence=True)
        identity = witness.guid(1)
        self.assertEqual(self.sample(9, hp=0)['death_observations'], {})
        observed = self.sample(10, hp=0, dead=True, active=False)
        self.assertEqual(observed['enemies'], {})
        self.assertEqual(observed['death_observations'][identity],
                         {'kind_id': 4, 'inherit_id': -1, 'hp': 0, 'active': False, 'is_dead': True,
                          'observer_sequence': 10, 'observed_at': 100})
        self.assertIsNone(self.sample(11, hp=0, dead=True, active=False, at=101))
        self.assertIsNone(self.sample(12, present=False, at=104))
        self.assertEqual(self.feed.latest['death_observations'], observed['death_observations'])
        self.assertEqual(self.sample(13, present=False, at=105)['death_observations'], {})

    def test_live_reappearance_and_guard_loss_clear_death_observation(self):
        fixture = self.fixture
        self.feed = EnemyLiveFeed(fixture.data, fixture.request, fixture.reference, death_evidence=True)
        self.assertTrue(self.sample(9, hp=0, dead=True)['death_observations'])
        self.assertEqual(self.sample(10, hp=0)['death_observations'], {})
        self.assertTrue(self.sample(11, hp=0, dead=True)['death_observations'])
        fixture.guard_path.write_text('{')
        self.assertNotIn('death_observations', self.feed.poll(now=100))
        self.assertEqual(self.sample(12, present=False)['death_observations'], {})

    def test_gap_or_lost_source_clears_continuity_and_old_samples_cannot_restore_it(self):
        self.feed.poll(now=100)
        gap = self.sample(11, hp=4)
        self.assertFalse(gap['continuous'])
        self.assertEqual(gap['enemies'][witness.guid(1)]['hp'], 4)
        self.fixture.enemy_path.write_text('{')
        loss = self.feed.poll(now=100)
        self.assertFalse(loss['available'])
        self.assertEqual(loss['enemies'], {})
        self.assertIsNone(self.feed.poll(now=100))
        self.assertIsNone(self.sample(11, hp=4))
        recovered = self.sample(12, hp=3)
        self.assertFalse(recovered['continuous'])
        self.assertTrue(recovered['available'])
        self.assertFalse(self.feed.poll(now=104)['available'])

    def test_another_checkpoint_cannot_rebase_the_running_feed(self):
        self.feed.poll(now=100)
        report, core = witness.report(), sample()
        report['sequence'] = 10
        core['sequence'] = 2
        for value in (report, core):
            value['state']['checkpoint']['save_guid'] = witness.guid(5)
        self.fixture.write(report, core=core)
        self.assertEqual(self.feed.poll(now=100)['reason'], 'checkpoint_changed')
        self.assertIsNone(self.sample(11))
        self.assertFalse(self.feed.latest['available'])

    def test_loopback_listener_receives_host_updates_and_cannot_propose_an_enemy_value(self):
        with Server(('127.0.0.1', 0), protocol_version=v1.VERSION, read_only=True) as server:
            server.publish('flag', FLAG, self.feed.poll(now=100))
            worker = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            try:
                with socket.create_connection(server.server_address, timeout=3) as connection:
                    with connection.makefile('rwb') as channel:
                        replica = join_replica(channel, protocol_version=v1.VERSION)
                        self.assertEqual(replica.sequence, 1)
                        observed = self.sample(10, hp=3)
                        server.publish('flag', FLAG, observed)
                        update = receive(channel, protocol_version=v1.VERSION)
                        self.assertTrue(replica.apply(update['data']))
                        self.assertEqual(replica.state['flags'][FLAG], observed)
                        send(channel, {'type': 'propose', 'kind': 'flag', 'target': FLAG, 'value': None},
                             protocol_version=v1.VERSION)
                        reply = receive(channel, protocol_version=v1.VERSION)
                        self.assertEqual(reply['type'], 'error')
                        self.assertIn('read-only', reply['message'])
                self.assertEqual(server.host_state.snapshot(), replica.snapshot())
            finally:
                server.shutdown()
                worker.join()


if __name__ == '__main__':
    unittest.main()
