import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lobby_sync import write_json
from session_replay import arm, load_trace
from steam_pose_bridge import CutsceneLink


class Wire:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def record_intro(directory, build):
    host = CutsceneLink(directory, 123, b'H')
    guest = CutsceneLink(directory / 'guest', 456, b'G')
    guest.local_file.parent.mkdir()
    scope = dict(session_id='a'*32, request_id='b'*32, attempt_id='c'*32, package_commit=build)
    links = [host, guest]
    for link in links:
        link.bind(scope, True)
    wires = [Wire(), Wire()]
    waiting = dict(event='evt_20011', occurrence=1, phase='waiting', vote=0, decision='none')
    playing = dict(waiting, phase='playing')
    request = dict(playing, vote=1, decision='request')
    accept = dict(playing, vote=1, decision='accept')
    ended = dict(request, phase='ended')
    for step in range(171):
        now, wall = step/10, 500 + step//10
        states = [waiting if step<15 else playing if step<90 else request if step<140 else ended,
                  None if step<5 else waiting if step<16 else playing if step<130 else accept if step<140 else dict(accept, phase='ended')]
        for link, state in zip(links, states):
            if state:
                write_json(link.local_file, dict(state, schema=1, game_pid=link.pid,
                                                 at=wall, attempt_id=scope['attempt_id']))
        for i, link in enumerate(links):
            outgoing = wires[1-i].messages
            messages, outgoing[:] = list(outgoing), []
            for message in messages or [None]:
                # Drop only guest replies during the host's first skip vote.
                if i==0 and message and message['type']=='cutscene_reply' and 90<=step<130:
                    message=None
                link.tick(wires[i], message, now, wall)
    for link in links:
        link.clear()
    return next(directory.glob('re2_coop_logs/*/scene-*.jsonl'))


class SessionReplayTests(unittest.TestCase):
    def test_host_records_lease_loss_and_confirmed_vote_from_simulated_guest(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        path = record_intro(directory, 'd'*40)
        trace = load_trace(path)
        self.assertFalse((directory/'guest/re2_coop_logs').exists())
        self.assertEqual(trace['end'], 'scope_closed')
        vote = next(g for g in trace['groups'] if g['host']['decision']=='request')
        replies = [s['peer'] and s['peer']['decision'] for s in vote['steps']]
        self.assertIn(False, replies)
        self.assertEqual(replies[-1], 'accept')
        self.assertLess(vote['steps'][0]['ms'], vote['steps'][-1]['ms'])
        self.assertNotIn('challenge', path.read_text())
        self.assertNotIn('game_pid', path.read_text())
        partial = directory/'partial.jsonl'
        partial.write_bytes(b'\n'.join(path.read_bytes().splitlines()[:-1])+b'\n{"ms":')
        self.assertEqual(load_trace(partial)['end'], 'partial')

    def test_arm_requires_current_solo_request_and_writes_only_the_replay_plan(self):
        from unittest.mock import patch
        game = Path(self.enterContext(TemporaryDirectory()))
        data=game/'reframework/data'
        data.mkdir(parents=True)
        (game/'re2-coop').mkdir()
        write_json(game/'re2-coop/build-info.json', {'source_commit':'d'*40})
        trace=load_trace(record_intro(game, 'e'*40))
        status=dict(schema=1, game_pid=55, attempt_id='e'*32, request_id='solo1', at=80, active=True)
        with patch('session_replay.time.time', return_value=100):
            write_json(data/'re2_coop_solo_status.json',status)
            with self.assertRaises(ValueError):
                arm(trace,game)
            write_json(data/'re2_coop_solo_status.json',dict(status,at=100))
            arm(trace,game)
        plan=json.loads((data/'re2_coop_scene_replay.json').read_bytes())
        self.assertEqual(plan['request_id'],'solo1')
        self.assertEqual(plan['groups'],trace['groups'])
        self.assertEqual(len(list(data.iterdir())),2)
