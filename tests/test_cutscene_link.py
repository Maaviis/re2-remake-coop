import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from lobby_sync import write_json
from protocol import v1
from steam_pose_bridge import CutsceneLink, envelope


class CutsceneLinkTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(self.enterContext(TemporaryDirectory()))
        self.link = CutsceneLink(self.data, 808, b'H')
        self.scope = dict(session_id='a'*32, request_id='b'*32, package_commit='c'*40, attempt_id='d'*32)
        self.link.bind(self.scope, True)
        self.wire = Mock()
        self.state = dict(event='evt_179', occurrence=3, phase='playing', vote=2, decision='request')

    def tick(self, now, msg=None):
        if msg:
            msg = v1.decode(v1.encode(msg, steam_pose=True), steam_pose=True)
        self.link.tick(self.wire, msg, now, 800 + int(now))
        return json.loads(self.link.peer_file.read_bytes())

    def latest(self):
        return self.wire.send.call_args.args[0]

    def test_only_one_live_response_per_poll_and_request_time_bounds_lease(self):
        self.tick(0)
        reply = {**self.latest(), 'type': 'cutscene_reply', 'role': 'G', 'state': self.state, 'age': 0}
        for field, other in (('role', 'H'), ('session_id', '0'*32), ('request_id', '0'*32),
                             ('package_commit', '0'*40), ('attempt_id', '0'*32), ('challenge', '0'*32)):
            with self.subTest(field=field):
                self.assertIsNone(self.tick(.1, {**reply, field: other})['peer'])
        self.assertEqual(self.tick(1.4, reply), dict(schema=1, game_pid=808, role='H',
                         attempt_id=self.scope['attempt_id'], at=800, peer=self.state))
        self.assertIsNone(self.tick(2.01, reply)['peer'])
        stale = {**reply, 'challenge': self.latest()['challenge']}
        self.assertIsNone(self.tick(4, stale)['peer'])
        self.assertNotEqual(self.latest()['challenge'], stale['challenge'])
        self.link.clear()
        self.assertFalse(self.link.peer_file.exists())
        self.link.bind(self.scope, True)
        self.assertIsNone(self.tick(4.1, stale)['peer'])

    def test_only_local_pid_attempt_and_fresh_observations_are_returned(self):
        self.tick(0)
        poll = envelope('cutscene_poll', **self.scope, role='G', challenge='7'*32)
        local = {**self.state, 'schema': 1, 'game_pid': 808, 'attempt_id': self.scope['attempt_id'], 'at': 799}
        for change in ({'at': 797}, {'at': 801}, {'game_pid': 807}, {'attempt_id': '4'*32},
                       {'occurrence': True}, {'decision': 'none'}, {'event': 'evt_-3'}, {'simulated': True}, {}):
            with self.subTest(change=change):
                write_json(self.link.local_file, {**local, **change})
                self.tick(.1, poll)
                response = self.latest()
                v1.encode(response, steam_pose=True)
                self.assertEqual(response['state'], None if change else self.state)
                self.assertEqual(response['age'], 0 if change else 1)
                self.assertEqual(response['role'], 'H')
                self.assertEqual(response['challenge'], poll['challenge'])

    def test_buffered_receive_cannot_publish_after_native_epoch_rejection(self):
        self.tick(0)
        reply = {**self.latest(), 'type': 'cutscene_reply', 'role': 'G', 'state': self.state, 'age': 0}
        self.wire.send.side_effect = OSError('old epoch')
        with self.assertRaises(OSError):
            self.tick(.01, reply)
        self.assertIsNone(json.loads(self.link.peer_file.read_bytes())['peer'])

    def test_fresh_polls_cannot_revive_old_occurrences_phases_or_declined_votes(self):
        now = 0
        def observe(state):
            nonlocal now
            now += .3
            self.tick(now)
            reply = {**self.latest(), 'type': 'cutscene_reply', 'role': 'G', 'state': state, 'age': 0}
            return self.tick(now + .01, reply)['peer']
        declined = {**self.state, 'decision': 'decline'}
        self.assertEqual(observe(declined), declined)
        for invalid in (self.state, {**declined, 'decision': 'accept'}, {**declined, 'phase': 'waiting'},
                        {**declined, 'occurrence': 2}, {**declined, 'vote': 1}):
            self.assertIsNone(observe(invalid))
        different = {**self.state, 'event': 'evt_23', 'occurrence': 1}
        self.assertEqual(observe(different), different)
        self.assertIsNone(observe(declined))
        repeated = {**self.state, 'occurrence': 4, 'phase': 'waiting', 'decision': 'none', 'vote': 0}
        self.assertEqual(observe(repeated), repeated)

    def test_wire_validation(self):
        poll = envelope('cutscene_poll', **self.scope, role='G', challenge='7'*32)
        with self.assertRaises(v1.ProtocolError):
            v1.encode(poll)
        for patch in ({'event': {}}, {'phase': 'skipped'}, {'decision': 'agree'}, {'occurrence': 0},
                      {'vote': True}, {'vote': 0}, {'event': 'evt_01'}, {'extra': 1}):
            with self.subTest(patch=patch), self.assertRaises(v1.ProtocolError):
                v1.encode({**poll, 'type': 'cutscene_reply', 'age': 0, 'state': {**self.state, **patch}},
                          steam_pose=True)
