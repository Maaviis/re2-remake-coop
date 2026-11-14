from copy import deepcopy
import unittest

from steam_pose_bridge import PoseHost, PoseGuest, make_proposal


def sample(sequence, position):
    return {"sequence": sequence, "run_id": "observer", "tdb": 70,
            "observed_at": 100, "position": position, "rotation": [0, 0, 0, 1]}


class SteamPoseTests(unittest.TestCase):
    def setUp(self):
        self.host = PoseHost("leon", "claire")
        self.guest = PoseGuest("leon", "claire")
        self.guest.receive(self.host.receive(self.guest.hello(), now=100))

    def test_both_directions_and_sequence(self):
        applied = self.host.local(sample(1, [1, 2, 3]), now=100)
        self.assertTrue(self.guest.receive(applied))
        proposed = self.host.receive(make_proposal("claire", sample(1, [4, 5, 6])), now=100)
        self.assertTrue(self.guest.receive(proposed))
        self.assertEqual(self.guest.replica.snapshot(), self.host.state.snapshot())
        self.assertEqual(self.host.state.state["players"]["leon"]["position"], [1, 2, 3])
        self.assertEqual(self.host.state.state["players"]["claire"]["position"], [4, 5, 6])

    def test_rejects_cross_player_authority_and_replay(self):
        foreign = make_proposal("leon", sample(1, [1, 2, 3]))
        self.assertIsNone(self.host.receive(foreign, now=100))
        forged = {"version": 1, "type": "propose", "kind": "door", "target": "lab", "value": "open"}
        self.assertIsNone(self.host.receive(forged, now=100))
        valid = make_proposal("claire", sample(2, [4, 5, 6]))
        self.assertIsNotNone(self.host.receive(valid, now=100))
        self.assertIsNone(self.host.receive(valid, now=100))
        # The peer's fresh local observation may have a different wall clock.
        skewed = make_proposal("claire", sample(3, [7, 8, 9]))
        self.assertIsNotNone(self.host.receive(skewed, now=3700))
        self.assertEqual(self.host.state.sequence, 2)
        changed_clock = make_proposal("claire", {**sample(4, [8, 9, 10]), "observed_at": 50})
        self.assertIsNotNone(self.host.receive(changed_clock, now=3700))
        self.assertEqual(self.host.state.sequence, 3)
        self.assertIsNone(self.host.local(sample(1, [1, 2, 3]), now=106),
                          "host observations still require local freshness")

    def test_gap_requires_authoritative_snapshot(self):
        self.host.local(sample(1, [1, 2, 3]), now=100)
        second = self.host.local(sample(2, [4, 5, 6]), now=100)
        self.assertFalse(self.guest.receive(second))
        self.assertFalse(self.guest.ready)
        corrupt = deepcopy(self.host.receive(self.guest.hello(), now=100))
        corrupt["data"]["digest"] = "a" * 64
        self.assertFalse(self.guest.receive(corrupt))
        self.assertFalse(self.guest.ready)
        self.assertTrue(self.guest.receive(self.host.receive(self.guest.hello(), now=100)))
        self.assertEqual(self.guest.replica.snapshot(), self.host.state.snapshot())

    def test_guest_rejects_replacement_without_transport_reset(self):
        replacement = PoseHost("leon", "claire")
        self.assertFalse(self.guest.receive(replacement.receive(self.guest.hello(), now=100)))
        self.assertFalse(self.guest.ready)
        self.guest.reset()
        self.assertTrue(self.guest.receive(replacement.receive(self.guest.hello(), now=100)))

    def test_valid_digest_does_not_bypass_pose_schema(self):
        from steam_pose_bridge import envelope
        value = make_proposal("leon", sample(1, [1, 2, 3]))["value"]
        value.pop("observed_at")
        event = self.host.state.emit("player", "leon", value)
        self.assertFalse(self.guest.receive(envelope("event", data=event)))
        self.assertFalse(self.guest.receive(envelope("snapshot", data=self.host.state.snapshot())))
        self.assertFalse(self.guest.ready)

    def test_old_snapshot_does_not_roll_back_on_local_link_loss(self):
        before = self.host.state.snapshot()
        self.guest.receive(self.host.local(sample(1, [1, 2, 3]), now=100))
        self.guest.ready = False
        self.assertFalse(self.guest.receive({"version": 1, "type": "snapshot", "data": before}))
        self.assertEqual(self.guest.replica.sequence, 1)

    def test_link_reset_hides_previous_guest_and_recovers_new_pose(self):
        self.host.receive(make_proposal("claire", sample(1, [1, 2, 3])), now=100)
        self.host.reset_link()
        stale = self.host.receive(self.guest.hello(), now=100)
        self.assertIsNone(stale["data"]["state"]["players"]["claire"]["position"])
        self.assertIsNone(self.host.receive(make_proposal("claire", sample(1, [4, 5, 6])), now=100))
        replay = self.host.receive(make_proposal("claire", sample(2, [4, 5, 6])), now=100)
        self.assertEqual(replay["data"]["value"]["position"], [4, 5, 6])


class SteamPoseBridgeIntegrationTests(unittest.TestCase):
    def test_bridges_export_opposite_poses_and_clear_on_disconnect(self):
        import json
        from pathlib import Path
        from queue import Empty, Queue
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep, time

        from protocol import v1
        from steam_pose_bridge import run_bridge

        connected, stop = Event(), Event()
        connected.set()

        class Link:
            def __init__(self, role, inbox, outbox):
                self.identity = role
                self.inbox, self.outbox = inbox, outbox
                self.role = self.epoch = None

            def receive(self):
                self.role = self.identity if connected.is_set() else None
                self.epoch = b"test-run" if self.role else None
                try:
                    return self.inbox.get_nowait() if self.role else None
                except Empty:
                    return None

            def send(self, value):
                self.outbox.put(v1.encode(value))

        with TemporaryDirectory() as temp:
            directories = [Path(temp) / name for name in ("host", "guest")]
            a, b = Queue(), Queue()
            errors = Queue()
            threads = []
            for directory, role, inbox, outbox, position in zip(
                    directories, (b"H", b"G"), (a, b), (b, a), ([1, 2, 3], [4, 5, 6])):
                directory.mkdir()
                local = {**sample(1, position), "source": "re2", "schema": 1,
                         "available": True, "observed_at": int(time())}
                (directory / "re2_coop_observer.json").write_text(json.dumps(local), encoding="utf-8")

                def run(path=directory, link=Link(role, inbox, outbox), kind=role):
                    try:
                        run_bridge(path, link, kind, "leon", "claire", stop=stop)
                    except Exception as exc:
                        errors.put(exc)

                thread = Thread(target=run)
                thread.start()
                threads.append(thread)

            def wait_for_pose(directory, expected):
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    if not errors.empty():
                        raise errors.get()
                    try:
                        result = json.loads((directory / "re2_coop_guest_pose.json").read_text(encoding="utf-8"))
                        if expected is None and not result["connected"]:
                            return result
                        if result["pose"] and result["pose"]["position"] == expected:
                            return result
                    except (FileNotFoundError, PermissionError):
                        pass
                    sleep(0.02)
                self.fail(f"did not receive expected pose {expected}")

            try:
                host = wait_for_pose(directories[0], [4, 5, 6])
                guest = wait_for_pose(directories[1], [1, 2, 3])
                self.assertEqual(host["session_id"], guest["session_id"])
                self.assertEqual(host["player_id"], "claire")
                self.assertEqual(guest["player_id"], "leon")
                connected.clear()
                for directory in directories:
                    self.assertIsNone(wait_for_pose(directory, None)["pose"])
            finally:
                stop.set()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
