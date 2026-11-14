from copy import deepcopy
import unittest
from unittest.mock import patch

from steam_pose_bridge import PoseHost, PoseGuest, make_proposal


def sample(sequence, position):
    return {"sequence": sequence, "run_id": "observer", "tdb": 70,
            "observed_at": 100, "position": position, "rotation": [0, 0, 0, 1]}


class SteamPoseTests(unittest.TestCase):
    def setUp(self):
        self.host = PoseHost("leon", "claire")
        self.guest = PoseGuest("leon", "claire")
        self.guest.receive(self.host.receive(self.guest.hello(), now=100))

    def guest_proposal(self, position_sample, *, player_id="claire"):
        return {**make_proposal(player_id, position_sample),
                "session_id": self.guest.replica.session_id}

    def test_both_directions_and_sequence(self):
        applied = self.host.local(sample(1, [1, 2, 3]), now=100)
        self.assertTrue(self.guest.receive(applied))
        proposed = self.host.receive(self.guest_proposal(sample(1, [4, 5, 6])), now=100)
        self.assertTrue(self.guest.receive(proposed))
        self.assertEqual(self.guest.replica.snapshot(), self.host.state.snapshot())
        self.assertEqual(self.host.state.state["players"]["leon"]["position"], [1, 2, 3])
        self.assertEqual(self.host.state.state["players"]["claire"]["position"], [4, 5, 6])

    def test_rejects_cross_player_authority_and_replay(self):
        foreign = self.guest_proposal(sample(1, [1, 2, 3]), player_id="leon")
        self.assertIsNone(self.host.receive(foreign, now=100))
        forged = {"version": 1, "type": "propose", "kind": "door", "target": "lab", "value": "open"}
        forged["session_id"] = self.guest.replica.session_id
        self.assertIsNone(self.host.receive(forged, now=100))
        valid = self.guest_proposal(sample(2, [4, 5, 6]))
        self.assertIsNotNone(self.host.receive(valid, now=100))
        self.assertIsNone(self.host.receive(valid, now=100))
        # The peer's fresh local observation may have a different wall clock.
        skewed = self.guest_proposal(sample(3, [7, 8, 9]))
        self.assertIsNotNone(self.host.receive(skewed, now=3700))
        self.assertEqual(self.host.state.sequence, 2)
        changed_clock = self.guest_proposal({**sample(4, [8, 9, 10]), "observed_at": 50})
        self.assertIsNotNone(self.host.receive(changed_clock, now=3700))
        self.assertEqual(self.host.state.sequence, 3)
        self.assertIsNone(self.host.local(sample(1, [1, 2, 3]), now=106),
                          "host observations still require local freshness")

    def test_retired_observer_run_cannot_restore_pose_after_link_reset(self):
        old = {**sample(8, [1, 2, 3]), "run_id": "initial"}
        current = {**sample(1, [4, 5, 6]), "run_id": "reloaded", "observed_at": 50}
        for observation in (old, current):
            event = self.host.receive(self.guest_proposal(observation), now=400)
            self.assertTrue(self.guest.receive(event))

        self.host.reset_link()
        self.guest.reset_link()
        snapshot = self.host.receive(self.guest.hello(), now=401)
        self.assertTrue(self.guest.receive(snapshot))
        # The delayed packet can have a sequence we have never seen.
        late = {**old, "sequence": 9}
        self.assertIsNone(self.host.receive(self.guest_proposal(late), now=401))
        self.assertEqual(self.host.state.snapshot(), self.guest.replica.snapshot())
        self.assertIsNone(self.host.state.state["players"]["claire"]["position"])

        live = {**current, "sequence": 2}
        self.assertTrue(self.guest.receive(self.host.receive(self.guest_proposal(live), now=401)))
        self.assertEqual(self.guest.replica.state["players"]["claire"]["position"], [4, 5, 6])
        # Run identifiers are scoped to the player.
        self.assertTrue(self.guest.receive(self.host.local(old, now=100)))

    def test_retired_run_limit_does_not_make_old_runs_valid_again(self):
        with patch("steam_pose_bridge.MAX_RETIRED_RUNS", 2):
            for run_id in ("first", "second", "third"):
                observation = {**sample(1, [1, 2, 3]), "run_id": run_id}
                self.assertIsNotNone(self.host.receive(self.guest_proposal(observation), now=400))
            before = self.host.state.snapshot()
            for run_id in ("fourth", "first"):
                observation = {**sample(2, [7, 8, 9]), "run_id": run_id}
                self.assertIsNone(self.host.receive(self.guest_proposal(observation), now=400))
                self.assertEqual(self.host.state.snapshot(), before)
            continuing = {**sample(2, [4, 5, 6]), "run_id": "third"}
            self.assertIsNotNone(self.host.receive(self.guest_proposal(continuing), now=400))


    def test_rejoin_snapshot_hides_expired_poses_without_allowing_replays(self):
        with patch("steam_pose_bridge.time.monotonic", return_value=50) as ticks:
            local = sample(1, [1, 2, 3])
            remote = self.guest_proposal(sample(1, [4, 5, 6]))
            self.host.local(local, now=100)
            self.host.receive(remote, now=400)
            ticks.return_value = 54
            before_expiry = self.host.receive(self.guest.hello(), now=105)
            self.assertEqual(before_expiry["data"]["state"]["players"]["leon"]["position"], [1, 2, 3])
            self.assertEqual(before_expiry["data"]["state"]["players"]["claire"]["position"], [4, 5, 6])

            ticks.return_value = 56
            # A new client has no previous observation key, and the host's
            # wall clock has moved backwards since recording the local pose.
            joined = PoseGuest("leon", "claire")
            snapshot = self.host.receive(joined.hello(), now=95)
            self.assertTrue(joined.receive(snapshot))
            for player in ("leon", "claire"):
                with self.subTest(player=player):
                    pose = joined.replica.state["players"][player]
                    self.assertIsNone(pose["position"])
                    self.assertIsNone(pose["rotation"])
                    self.assertEqual(pose["observer_sequence"], 1)
            self.assertEqual(joined.replica.snapshot(), self.host.state.snapshot())
            self.assertIsNone(self.host.local(local, now=100))
            self.assertIsNone(self.host.receive(remote, now=406))
            self.assertTrue(joined.receive(self.host.local(sample(2, [7, 8, 9]), now=100)))

    def test_connected_guest_applies_expiry_events_once_in_sequence(self):
        with patch("steam_pose_bridge.time.monotonic", return_value=50) as ticks:
            local = {**sample(1, [1, 2, 3]), "motion": {
                "bank": 1, "id": 160, "name": "idle", "frame": 2, "end_frame": 10,
            }}
            self.assertTrue(self.guest.receive(self.host.local(local, now=100)))
            remote = self.guest_proposal(sample(1, [4, 5, 6]))
            self.assertTrue(self.guest.receive(self.host.receive(remote, now=200)))

            ticks.return_value = 55
            events = self.host.expire_poses()
            self.assertEqual([event["data"]["sequence"] for event in events], [3, 4])
            for event in events:
                self.assertIsNone(event["data"]["value"]["position"])
                self.assertNotIn("motion", event["data"]["value"])
                self.assertTrue(self.guest.receive(event))
            self.assertEqual(self.host.expire_poses(), [])
            self.assertEqual(self.guest.replica.snapshot(), self.host.state.snapshot())


    def test_snapshot_uses_remaining_source_window_for_host_pose(self):
        with patch("steam_pose_bridge.time.monotonic", return_value=50) as ticks:
            self.host.local(sample(1, [1, 2, 3]), now=104)
            self.host.receive(self.guest_proposal(sample(1, [4, 5, 6])), now=104)
            ticks.return_value = 52
            snapshot = self.host.receive(self.guest.hello(), now=106)
            players = snapshot["data"]["state"]["players"]
            self.assertIsNone(players["leon"]["position"])
            self.assertEqual(players["claire"]["position"], [4, 5, 6])

    def test_delayed_guest_proposal_cannot_enter_a_restarted_host_session(self):
        delayed = self.guest_proposal(sample(5, [4, 5, 6]))
        replacement = PoseHost("leon", "claire")
        self.guest.reset_link()
        snapshot = replacement.receive(self.guest.hello(), now=100)
        self.assertIsNone(replacement.receive(delayed, now=100))
        self.assertEqual(replacement.state.snapshot(), snapshot["data"])

        self.assertTrue(self.guest.receive(snapshot))
        current = self.guest_proposal(sample(6, [7, 8, 9]))
        self.assertTrue(self.guest.receive(replacement.receive(current, now=100)))
        self.assertEqual(self.guest.replica.snapshot(), replacement.state.snapshot())


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

    def test_guest_ignores_delayed_snapshot_from_previous_request(self):
        previous = self.host.receive(self.guest.hello(), now=100)
        self.guest.reset_link()
        self.assertFalse(self.guest.receive(previous), "a snapshot needs an outstanding hello")
        replacement = PoseHost("leon", "claire")
        request = self.guest.hello()
        fresh = replacement.receive(request, now=100)
        self.assertNotEqual(previous["request_id"], request["request_id"])
        self.assertEqual(request["request_id"], fresh["request_id"])
        self.assertEqual(self.guest.hello(), request, "retry keeps the outstanding request")
        self.assertFalse(self.guest.receive(previous))
        self.assertEqual(self.guest.replica.session_id, self.host.state.session_id)
        self.assertTrue(self.guest.receive(fresh))
        self.assertEqual(self.guest.replica.session_id, replacement.state.session_id)
        self.assertFalse(self.guest.receive(fresh), "request was consumed")
        self.assertTrue(self.guest.ready)

    def test_replacement_with_invalid_digest_keeps_existing_replica(self):
        self.assertTrue(self.guest.receive(self.host.local(sample(1, [1, 2, 3]), now=100)))
        original = self.guest.replica.snapshot()
        self.guest.reset_link()
        replacement = PoseHost("leon", "claire")
        candidate = replacement.receive(self.guest.hello(), now=100)
        corrupt = deepcopy(candidate)
        corrupt["data"]["digest"] = "0" * 64
        self.assertFalse(self.guest.receive(corrupt))
        self.assertEqual(self.guest.replica.snapshot(), original)
        self.assertFalse(self.guest.ready)
        self.assertTrue(self.guest.receive(candidate))
        self.assertEqual(self.guest.replica.snapshot(), replacement.state.snapshot())

    def test_snapshot_needs_request_even_during_active_session(self):
        replacement = PoseHost("leon", "claire")
        request = PoseGuest("leon", "claire").hello()
        self.assertFalse(self.guest.receive(replacement.receive(request, now=100)))
        self.assertTrue(self.guest.ready)
        self.assertEqual(self.guest.replica.session_id, self.host.state.session_id)


    def test_valid_digest_does_not_bypass_pose_schema(self):
        from steam_pose_bridge import envelope
        value = self.guest_proposal(sample(1, [1, 2, 3]), player_id="leon")["value"]
        value.pop("observed_at")
        event = self.host.state.emit("player", "leon", value)
        self.assertFalse(self.guest.receive(envelope("event", data=event)))
        request = self.guest.hello()
        snapshot = self.host.receive(request, now=100)
        self.assertFalse(self.guest.receive(snapshot))
        self.assertFalse(self.guest.ready)

    def test_old_snapshot_does_not_roll_back_on_local_link_loss(self):
        self.guest.reset_link()
        before = self.host.receive(self.guest.hello(), now=100)
        self.assertTrue(self.guest.receive(before))
        self.guest.receive(self.host.local(sample(1, [1, 2, 3]), now=100))
        self.guest.reset_link()
        request = self.guest.hello()
        stale = {**before, "request_id": request["request_id"]}
        self.assertFalse(self.guest.receive(stale))
        self.assertEqual(self.guest.replica.sequence, 1)

    def test_link_reset_hides_previous_guest_and_recovers_new_pose(self):
        self.host.receive(self.guest_proposal(sample(1, [1, 2, 3])), now=100)
        self.host.reset_link()
        stale = self.host.receive(self.guest.hello(), now=100)
        self.assertIsNone(stale["data"]["state"]["players"]["claire"]["position"])
        self.assertIsNone(self.host.receive(self.guest_proposal(sample(1, [4, 5, 6])), now=100))
        replay = self.host.receive(self.guest_proposal(sample(2, [4, 5, 6])), now=100)
        self.assertEqual(replay["data"]["value"]["position"], [4, 5, 6])


class SteamPoseBridgeIntegrationTests(unittest.TestCase):
    def test_bridges_export_opposite_poses_and_clear_on_expiry_or_disconnect(self):
        import json
        from pathlib import Path
        from queue import Empty, Queue
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep, time

        from steam_pose_bridge import _encode, run_bridge

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
                self.outbox.put(_encode(value))

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

            def wait_for_pose(directory, expected, *, connected=True, min_sequence=0):
                deadline = monotonic() + 7
                while monotonic() < deadline:
                    if not errors.empty():
                        raise errors.get()
                    try:
                        result = json.loads((directory / "re2_coop_guest_pose.json").read_text(encoding="utf-8"))
                        if result["connected"] == connected:
                            if result["pose"] is None and expected is None:
                                if not connected or result["sequence"] >= min_sequence:
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
                last_pose_sequence = max(host["sequence"], guest["sequence"])
                for directory in directories:
                    # The host emits one event per expired player while the
                    # link stays up, rather than the output lease alone hiding it.
                    wait_for_pose(directory, None, min_sequence=last_pose_sequence + 2)
                connected.clear()
                for directory in directories:
                    wait_for_pose(directory, None, connected=False)
            finally:
                stop.set()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())

    def test_guest_rejoins_restarted_host_after_multiple_timeouts(self):
        import json
        from pathlib import Path
        from queue import Empty, Queue
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep, time
        from unittest.mock import patch

        from steam_pose_bridge import _encode, run_bridge

        connected = Event()
        connected.set()
        stops = [Event(), Event()]

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
                self.outbox.put(_encode(value))

        with (TemporaryDirectory() as temp,
              patch("steam_pose_bridge.PEER_TIMEOUT", 0.4),
              patch("steam_pose_bridge.RETRY_INTERVAL", 0.05)):
            directories = [Path(temp) / name for name in ("host", "guest")]
            leon_motion = {"bank": 1, "id": 160,
                           "name": "pl00_0160_OFF_Gazing_Idle_F_Loop",
                           "frame": 550.0, "end_frame": 1100.0}
            a, b = Queue(), Queue()
            errors = Queue()
            threads = []
            def run(path, link, kind, halt):
                try:
                    run_bridge(path, link, kind, "leon", "claire", stop=halt)
                except Exception as exc:
                    errors.put(exc)

            for index, (directory, role, inbox, outbox, position) in enumerate(zip(
                    directories, (b"H", b"G"), (a, b), (b, a), ([1, 2, 3], [4, 5, 6]))):
                directory.mkdir()
                local = {**sample(1, position), "source": "re2", "schema": 1,
                         "available": True, "observed_at": int(time())}
                if role == b"H":
                    local["motion"] = leon_motion
                (directory / "re2_coop_observer.json").write_text(json.dumps(local), encoding="utf-8")

                thread = Thread(target=run, args=(directory, Link(role, inbox, outbox),
                                                  role, stops[index]))
                thread.start()
                threads.append(thread)

            def wait_for_pose(directory, expected, *, other_session=None):
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    if not errors.empty():
                        raise errors.get()
                    try:
                        result = json.loads((directory / "re2_coop_guest_pose.json").read_text(encoding="utf-8"))
                        if other_session is not None and result["session_id"] == other_session:
                            sleep(0.02)
                            continue
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
                self.assertEqual(guest["pose"]["motion"], leon_motion)
                original_session = guest["session_id"]
                stops[0].set()
                threads[0].join(2)
                self.assertFalse(threads[0].is_alive())
                self.assertIsNone(wait_for_pose(directories[1], None)["pose"])
                # Let the offline guest retry across multiple peer timeouts.
                sleep(0.9)
                replacement_stop = Event()
                stops.append(replacement_stop)
                replacement = Thread(target=run, args=(directories[0], Link(b"H", a, b),
                                                       b"H", replacement_stop))
                replacement.start()
                threads.append(replacement)
                renewed = wait_for_pose(directories[1], [1, 2, 3],
                                        other_session=original_session)
                self.assertNotEqual(renewed["session_id"], original_session)
                self.assertEqual(renewed["pose"]["motion"], leon_motion)
                connected.clear()
                for directory in directories:
                    self.assertIsNone(wait_for_pose(directory, None)["pose"])
            finally:
                for halt in stops:
                    halt.set()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
