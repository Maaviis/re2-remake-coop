from copy import deepcopy
import unittest
from unittest.mock import call, patch

from steam_pose_bridge import PoseHost, PoseGuest, SteamPipe, make_proposal


def sample(sequence, position):
    return {"sequence": sequence, "run_id": "observer", "tdb": 70,
            "observed_at": 100, "position": position, "rotation": [0, 0, 0, 1]}


class SteamPosePipeTests(unittest.TestCase):
    def test_window_pause_rejection_reaches_lobby_actions(self):
        pipe = SteamPipe(123)
        rejection = b"error return to the RE2 window and retry this command"
        for action, args in ((pipe.create_lobby, ()), (pipe.join_invite, (4,)),
                             (pipe.leave_lobby, (5,)), (pipe.invite_dialog, ()), (pipe.protect_campaign, ())):
            with (self.subTest(action=action.__name__), patch.object(pipe, "lobby_status", return_value="idle"),
                  patch.object(pipe, "request", return_value=rejection),
                  self.assertRaisesRegex(ValueError, "Zum RE2-Fenster zurückkehren")):
                action(*args)

    def test_batch_is_consumed_in_order_before_reading_the_pipe_again(self):
        pipe = SteamPipe(123, batch_reads=True)
        with patch.object(pipe, "request", side_effect=[b"BGepoch001\x00\x03one\x00\x03two", b"N"]) as request:
            self.assertEqual(pipe.receive(), b"one")
            self.assertEqual((pipe.role, pipe.epoch), (b"G", b"epoch001"))
            self.assertEqual(pipe.receive(), b"two")
            request.assert_called_once_with(b"B")
            self.assertIsNone(pipe.receive())
            self.assertEqual((pipe.role, pipe.epoch), (None, None))

    def test_falls_back_to_single_frame_reads_with_an_older_plugin(self):
        pipe = SteamPipe(123, batch_reads=True)
        with patch.object(pipe, "request", side_effect=[b"E", b"Hepoch001one", b"Hepoch001two"]) as request:
            self.assertEqual(pipe.receive(), b"one")
            self.assertEqual(pipe.receive(), b"two")
            self.assertEqual(request.call_args_list, [call(b"B"), call(b"R"), call(b"R")])

    def test_truncated_batch_does_not_publish_its_first_frame_or_epoch(self):
        pipe = SteamPipe(123, batch_reads=True)
        with patch.object(pipe, "request", side_effect=[b"BGepoch001\x00\x03one\x00\x03tw", b"N"]) as request:
            with self.assertRaises(OSError):
                pipe.receive()
            self.assertEqual((pipe.role, pipe.epoch), (None, None))
            self.assertIsNone(pipe.receive())
            self.assertEqual(request.call_args_list, [call(b"B"), call(b"B")])

    def test_failed_send_drops_buffered_frames_before_reading_the_new_epoch(self):
        pipe = SteamPipe(123, batch_reads=True)
        with patch.object(pipe, "request", side_effect=[b"BGepoch001\x00\x03one\x00\x03two",
                                                       b"E", b"Gepoch002three"]):
            self.assertEqual(pipe.receive(), b"one")
            with self.assertRaises(OSError):
                pipe.send_payload(b"proposal")
            self.assertEqual(pipe.receive(), b"three")
            self.assertEqual(pipe.epoch, b"epoch002")

    def test_leaving_the_lobby_discards_remaining_frames(self):
        pipe = SteamPipe(123, batch_reads=True)
        with patch.object(pipe, "request", side_effect=[b"BGepoch001\x00\x03one\x00\x03two",
                                                       b"accepted leave", b"N"]) as request:
            self.assertEqual(pipe.receive(), b"one")
            pipe.leave_lobby(1)
            self.assertIsNone(pipe.receive())
            self.assertEqual(request.call_args_list, [call(b"B"), call(b"leave 1", pipe_name=pipe.lobby_name),
                                                      call(b"B")])


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

    def test_campaign_pose_tag_survives_both_directions_but_never_absence(self):
        from guest_pose import _pose

        attempt = "a" * 32
        area = {"scenario": 1, "map": 112, "area": 5}
        local = {**sample(1, [1, 2, 3]), "campaign_attempt_id": attempt, "campaign_area": area}
        remote = {**sample(1, [4, 5, 6]), "campaign_attempt_id": attempt, "campaign_area": area}
        self.assertTrue(self.guest.receive(self.host.local(local, now=100)))
        self.assertTrue(self.guest.receive(self.host.receive(self.guest_proposal(remote), now=100)))
        for player in ("leon", "claire"):
            pose = _pose(self.guest.replica.state["players"][player])
            self.assertEqual((pose["campaign_attempt_id"], pose["campaign_area"]), (attempt, area))
            self.assertEqual((pose["observer_run_id"], pose["observer_sequence"]), ("observer", 1))

        absent = {**sample(2, None), "rotation": None}
        self.assertIsNone(self.host.receive(self.guest_proposal({**absent, "campaign_attempt_id": attempt}), now=100))
        self.assertIsNone(self.host.receive(self.guest_proposal({**remote, "sequence": 2,
                                                                "campaign_attempt_id": "wrong"}), now=100))
        event = self.host.receive(self.guest_proposal(absent), now=100)
        self.assertTrue(self.guest.receive(event))
        self.assertIsNone(_pose(self.guest.replica.state["players"]["claire"]))
        with patch("steam_pose_bridge.time.monotonic", return_value=float("inf")):
            events = self.host.expire_poses()
        self.assertEqual(len(events), 1)
        self.assertTrue(self.guest.receive(events[0]))
        self.assertNotIn("campaign_attempt_id", self.guest.replica.state["players"]["leon"])
        self.assertNotIn("campaign_area", self.guest.replica.state["players"]["leon"])

    def test_new_hello_cannot_receive_a_scoped_pose_in_its_first_snapshot(self):
        host = PoseHost("leon", "claire", lobby_config={})
        host.receive(self.guest.hello(), now=100)
        host.local({**sample(1, [1, 2, 3]), "campaign_attempt_id": "a" * 32}, now=100)
        replacement = PoseGuest("leon", "claire")
        snapshot = host.receive(replacement.hello(), now=100)
        state = snapshot["data"]["state"]["players"]["leon"]
        self.assertIsNone(state["position"])
        self.assertNotIn("campaign_attempt_id", state)
        self.assertTrue(replacement.receive(snapshot))

    def test_new_campaign_requires_the_area_capability(self):
        from protocol import v1

        legacy = {"version": 1, "type": "campaign_pose_capability", "session_id": "fixture",
                  "request_id": "a" * 32}
        with self.assertRaises(v1.ProtocolError):
            v1.encode(legacy, steam_pose=True)
        for version in (0, True, 2):
            with self.assertRaises(v1.ProtocolError):
                v1.encode({**legacy, "area_version": version}, steam_pose=True)
        with self.assertRaises(v1.ProtocolError):
            v1.encode({**legacy, "area_version": 1}, steam_pose=True)
        for version in (2, True, "3"):
            with self.assertRaises(v1.ProtocolError):
                v1.encode({**legacy, "area_version": 1, "enemy_version": version}, steam_pose=True)
        capable = {**legacy, "area_version": 1, "enemy_version": 3}
        self.assertEqual(v1.decode(v1.encode(capable, steam_pose=True), steam_pose=True), capable)
        for version in (1, 2, True, "3"):
            with self.assertRaises(v1.ProtocolError):
                v1.encode({**capable, "resume_version": version}, steam_pose=True)
        current = {**capable, "resume_version": v1.CAMPAIGN_RESUME_VERSION}
        self.assertEqual(v1.decode(v1.encode(current, steam_pose=True), steam_pose=True), current)

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
        late = {**old, "sequence": 9}
        self.assertIsNone(self.host.receive(self.guest_proposal(late), now=401))
        self.assertEqual(self.host.state.snapshot(), self.guest.replica.snapshot())
        self.assertIsNone(self.host.state.state["players"]["claire"]["position"])

        live = {**current, "sequence": 2}
        self.assertTrue(self.guest.receive(self.host.receive(self.guest_proposal(live), now=401)))
        self.assertEqual(self.guest.replica.state["players"]["claire"]["position"], [4, 5, 6])
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
        value = make_proposal("leon", sample(1, [1, 2, 3]))["value"]
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
    def test_guest_drains_both_pose_streams_before_the_native_queue_overflows(self):
        from collections import deque
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from time import time as wall_time
        from types import SimpleNamespace

        from guest_pose import PoseFile
        from steam_pose_bridge import _encode, run_bridge

        class Clock:
            elapsed = 10.0
            time = staticmethod(wall_time)

            def monotonic(self):
                return self.elapsed

            def sleep(self, duration):
                self.elapsed += duration

        clock = Clock()
        host = PoseHost("leon", "claire")

        class Link:
            role, epoch = b"G", b"test-peer"

            def __init__(self):
                self.queue = deque()
                self.peak_queue = 0
                self.next_sample = None
                self.sample_number = 0

            def receive(self):
                clock.sleep(0.01)
                while self.next_sample is not None and self.next_sample <= clock.monotonic():
                    # Two observers at 10 Hz emit two authoritative events on each tick.
                    now = int(wall_time())
                    self.sample_number += 1
                    observation = {**sample(self.sample_number, [self.sample_number, 2, 3]), "observed_at": now}
                    self.queue.append(host.local(observation, now=now))
                    proposal = {**make_proposal("claire", observation), "session_id": host.state.session_id}
                    self.queue.append(host.receive(proposal, now=now))
                    self.next_sample += 0.1
                self.peak_queue = max(self.peak_queue, len(self.queue))
                if self.peak_queue > 32:
                    raise AssertionError("the guest overflowed the 32-message native queue")
                return _encode(self.queue.popleft()) if self.queue else None

            def send(self, message):
                reply = host.receive(message, now=int(wall_time()))
                if reply is not None:
                    self.queue.append(reply)
                if message["type"] == "hello" and self.next_sample is None:
                    self.next_sample = clock.monotonic() + 0.1

        applied = []

        class RecordingPoseFile(PoseFile):
            def update(self, replica):
                super().update(replica)
                applied.append(replica.sequence)

        link = Link()
        with (TemporaryDirectory() as temp, patch("steam_pose_bridge.time", clock),
              patch("steam_pose_bridge.PoseFile", RecordingPoseFile)):
            stop = SimpleNamespace(is_set=lambda: clock.elapsed >= 20.0)
            run_bridge(Path(temp), link, b"G", "leon", "claire", stop=stop)

        self.assertGreater(applied[-1], 180)
        self.assertLessEqual(host.state.sequence - applied[-1], 4)
        self.assertLessEqual(link.peak_queue, 4)

    def test_cli_tracks_the_open_game_handle_until_exit(self):
        import sys
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import Mock

        import steam_pose_bridge

        waits = Mock(side_effect=[258, 0])
        windows = SimpleNamespace(SYNCHRONIZE=0x100000, WAIT_OBJECT_0=0, OpenProcess=Mock(return_value=81),
                                  WaitForSingleObject=waits, CloseHandle=Mock())

        def run_until_game_exits(_, transport, role, *args, stop, **kwargs):
            self.assertEqual((transport.game_pid, role), (1234, b'G'))
            self.assertFalse(stop.is_set())
            self.assertTrue(stop.is_set())

        with TemporaryDirectory() as data:
            argv = ['steam_pose_bridge.py', '--role', 'guest', '--pid', '1234', '--data', data]
            with (patch.object(sys, 'argv', argv), patch.object(sys, 'platform', 'win32'),
                  patch.dict(sys.modules, {'_winapi': windows}),
                  patch.object(steam_pose_bridge, 'run_bridge', side_effect=run_until_game_exits)):
                self.assertEqual(steam_pose_bridge.main(), 0)
        windows.OpenProcess.assert_called_once_with(windows.SYNCHRONIZE, False, 1234)
        self.assertEqual(waits.call_args_list, [call(81, 0), call(81, 0)])
        windows.CloseHandle.assert_called_once_with(81)

    def test_automatic_bridge_switches_to_guest_for_steam_invite_and_back_after_leave(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep, time

        from lobby_control import submit
        from lobby_sync import write_json
        from steam_pose_bridge import SteamPipe, run_automatic_bridge
        from load_preflight import NativeSaveSource
        from unittest.mock import Mock

        pipe = SteamPipe(123)
        claimed, confirmed, left, stop = Event(), Event(), Event(), Event()
        rejected, retried = Event(), Event()
        offered = Event()

        def request(command, *, pipe_name=None):
            if pipe_name is None:
                self.assertEqual(command, b"R")
                return b"N"
            self.assertEqual(pipe_name, pipe.lobby_name)
            if command == b"status":
                if left.is_set() or not offered.is_set():
                    return b"idle"
                if confirmed.is_set():
                    return b"joined"
                if rejected.is_set() and not retried.is_set():
                    return b"invite-pending"
                return b"joining" if claimed.is_set() else b"invite-pending"
            if command == b"invite-revision":
                return b"8" if rejected.is_set() else b"7"
            if command == b"join-error 7":
                return b"join-failed Steam lobby no longer exists"
            if command == b"membership-revision":
                return b"9"
            if command == b"leave 9":
                left.set()
                return b"accepted leave"
            if command == b"join-invite 8":
                retried.set()
                return b"accepted join-invite"
            self.assertEqual(command, b"join-invite 7")
            claimed.set()
            return b"accepted join-invite"

        with TemporaryDirectory() as temp, patch.object(pipe, "request", side_effect=request):
            data = Path(temp)
            source = NativeSaveSource(data, data.resolve(), allow_date='2026-04-08')
            prepare = Mock(return_value=(source, Mock()))
            failure = "Steam Cloud wurde waehrend der Vorbereitung aktiviert."
            thread = Thread(target=run_automatic_bridge, args=(data, pipe, "leon", "claire"),
                            kwargs={"stop": stop, "enable_campaign": prepare,
                                    "campaign_setup_status": lambda: ("failed", failure)})

            def wait_for_invite(predicate):
                deadline = monotonic() + 4
                while monotonic() < deadline:
                    try:
                        result = json.loads((data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
                    except (FileNotFoundError, PermissionError):
                        result = None
                    if result is not None and predicate(result):
                        return result
                    sleep(0.02)
                self.fail("bridge did not publish the expected invitation state")

            thread.start()
            try:
                initial = wait_for_invite(lambda status: status["role"] == "H" and status["steam_lobby"] == "idle")
                setup = initial["campaign_setup"]
                self.assertNotIn("campaign_start_supported", initial)
                self.assertEqual(initial["campaign_setup_status"], "failed")
                self.assertEqual(initial["campaign_setup_error"], failure)
                write_json(data / "re2_coop_lobby_command.json", {
                    "id": "old-campaign-setup", "written_at": int(time()), **setup, "revision": 2,
                    "action": "prepare-campaign", "value": True,
                })
                wait_for_invite(lambda status: status["error"] == "command expired or lobby changed")
                prepare.assert_not_called()
                write_json(data / "re2_coop_lobby_command.json", {
                    "id": "campaign-setup", "written_at": int(time()), **setup,
                    "action": "prepare-campaign", "value": True,
                })
                prepared = wait_for_invite(lambda status: status.get("campaign_start_supported"))
                self.assertNotIn("campaign_setup", prepared)
                self.assertNotIn("campaign_setup_error", prepared)
                self.assertIsNone(prepared["error"])
                prepare.assert_called_once_with()
                offered.set()
                offer = wait_for_invite(lambda status: "steam_invite" in status)["steam_invite"]
                self.assertEqual(offer["revision"], 7)
                write_json(data / "re2_coop_lobby_command.json", {
                    "id": "expired-offer", "written_at": int(time()), "session_id": offer["session_id"],
                    "revision": 6, "action": "join-invite", "value": True,
                })
                wait_for_invite(lambda status: status["error"] == "command expired or lobby changed")
                self.assertFalse(claimed.is_set())
                submit(data, "join-invite", True)
                self.assertTrue(claimed.wait(2))
                wait_for_invite(lambda status: status["steam_lobby"] == "joining")
                rejected.set()
                available = wait_for_invite(lambda status: status["steam_lobby"] == "invite-pending")
                self.assertEqual(available["error"], "Steam lobby no longer exists")
                self.assertEqual(available["steam_invite"]["revision"], 8)
                submit(data, "join-invite", True)
                self.assertTrue(retried.wait(2))
                wait_for_invite(lambda status: status["steam_lobby"] == "joining")
                confirmed.set()
                joined = wait_for_invite(lambda status: status["steam_lobby"] == "joined")
                self.assertEqual((joined["role"], joined["campaign_start_supported"]), ("G", True))
                self.assertNotIn("steam_invite", joined)
                self.assertFalse(joined["connected"])
                self.assertIsNone(joined["lobby"])
                self.assertIsNone(joined["error"])
                with self.assertRaisesRegex(ValueError, "current Steam invite"):
                    submit(data, "join-invite", True)
                membership = joined["steam_membership"]
                write_json(data / "re2_coop_lobby_command.json", {
                    "id": "old-membership", "written_at": int(time()), "session_id": membership["session_id"],
                    "revision": 8, "action": "leave", "value": True,
                })
                wait_for_invite(lambda status: status["error"] == "command expired or lobby changed")
                self.assertFalse(left.is_set())
                submit(data, "leave", True)
                self.assertTrue(left.wait(2))
                returned = wait_for_invite(lambda status: status["role"] == "H" and status["steam_lobby"] == "idle")
                self.assertIs(returned["campaign_start_supported"], True)
                self.assertNotIn("steam_membership", returned)
                with self.assertRaisesRegex(ValueError, "current Steam lobby membership"):
                    submit(data, "leave", True)
            finally:
                stop.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_host_waits_for_native_lobby_confirmation_before_inviting(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep

        from lobby_control import submit
        from steam_pose_bridge import SteamPipe, run_bridge

        pipe = SteamPipe(123)
        native_owned = Event()
        native_overlay = Event()
        pipe_requests = []

        def request(command, *, pipe_name=None):
            if pipe_name is None:
                self.assertEqual(command, b"R")
                return b"N"
            self.assertEqual(pipe_name, pipe.lobby_name)
            if command == b"status":
                if native_owned.is_set():
                    return b"owned"
                return b"creating" if b"create" in pipe_requests else b"idle"
            if command == b"membership-revision":
                return b"1"
            pipe_requests.append(command)
            if command == b"invite-dialog" and not native_overlay.is_set():
                return b"error Steam overlay is unavailable"
            return b"accepted " + command

        with TemporaryDirectory() as temp, patch.object(pipe, "request", side_effect=request):
            data = Path(temp)
            stopped = Event()
            thread = Thread(target=run_bridge, args=(data, pipe, b"H", "leon", "claire"),
                            kwargs={"stop": stopped, "lobby_enabled": True})

            def wait_for_steam_state(expected):
                deadline = monotonic() + 4
                while monotonic() < deadline:
                    try:
                        state = json.loads((data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
                    except (FileNotFoundError, PermissionError):
                        sleep(0.02)
                        continue
                    if state["steam_lobby"] == expected:
                        return state
                    sleep(0.02)
                self.fail(f"bridge did not publish Steam lobby state {expected}")

            thread.start()
            try:
                self.assertFalse(wait_for_steam_state("idle")["connected"])
                submit(data, "create", True)
                self.assertFalse(wait_for_steam_state("creating")["connected"])
                with self.assertRaisesRegex(ValueError, "idle Steam plugin"):
                    submit(data, "create", True)
                submit(data, "invite", True)
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    state = wait_for_steam_state("creating")
                    if state["error"] == "Steam invitation control is unavailable":
                        break
                    sleep(0.02)
                else:
                    self.fail("bridge did not report the premature invite as rejected")
                self.assertEqual(pipe_requests, [b"create"])
                native_owned.set()
                self.assertFalse(wait_for_steam_state("owned")["connected"])
                submit(data, "invite", True)
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    state = wait_for_steam_state("owned")
                    if state["error"] == "Steam overlay is unavailable":
                        break
                    sleep(0.02)
                else:
                    self.fail("bridge hid the native overlay error")
                self.assertEqual(pipe_requests, [b"create", b"invite-dialog"])
                native_overlay.set()
                submit(data, "invite", True)
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    if pipe_requests.count(b"invite-dialog") == 2 and wait_for_steam_state("owned")["error"] is None:
                        break
                    sleep(0.02)
                else:
                    self.fail("bridge did not clear the recovered invitation error")
            finally:
                stopped.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(wait_for_steam_state("unavailable")["connected"])

    def test_waiting_guest_reuses_request_across_peer_timeouts(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import sleep
        from unittest.mock import patch

        from steam_pose_bridge import run_bridge

        class SilentLink:
            role = b"G"
            epoch = b"same-peer"

            def __init__(self):
                self.sent = []

            def receive(self):
                return None

            def send(self, message):
                self.sent.append(message)

        with (TemporaryDirectory() as temp,
              patch("steam_pose_bridge.PEER_TIMEOUT", 0.15),
              patch("steam_pose_bridge.RETRY_INTERVAL", 0.05)):
            link = SilentLink()
            stop = Event()
            thread = Thread(target=run_bridge,
                            args=(Path(temp), link, b"G", "leon", "claire"),
                            kwargs={"stop": stop})
            thread.start()
            try:
                sleep(0.6)
            finally:
                stop.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            requests = [message["request_id"] for message in link.sent
                        if message["type"] == "hello"]
            self.assertGreaterEqual(len(requests), 3)
            self.assertEqual(len(set(requests)), 1)

    def test_guest_can_leave_as_soon_as_the_first_pose_arrives(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event
        from time import time
        from types import SimpleNamespace

        from guest_pose import PoseFile
        from lobby_control import submit
        from steam_pose_bridge import _encode, run_bridge

        host = PoseHost("leon", "claire")
        now = int(time())
        host.local({**sample(1, [1, 2, 3]), "observed_at": now}, now=now)
        stop = Event()
        departures = []

        class Link:
            role = epoch = snapshot = None

            def lobby_status(self):
                return "joined" if self.epoch is not None else "idle"

            def membership_revision(self):
                return 7 if self.epoch is not None else None

            def receive(self):
                if self.epoch is None:
                    self.role, self.epoch = b"G", b"new-peer"
                    return None
                if self.snapshot is None:
                    raise AssertionError("expected the guest hello or a completed leave")
                result, self.snapshot = self.snapshot, None
                return result

            def send(self, message):
                self.snapshot = _encode(host.receive(message, now=now))

            def leave_lobby(self, revision):
                departures.append(revision)
                stop.set()

        with TemporaryDirectory() as temp:
            data = Path(temp)

            class LeavingReceiver(PoseFile):
                def update(self, replica):
                    super().update(replica)
                    submit(data, "leave", True)

            # Complete the handshake within the very first native status polling interval.
            bridge_clock = SimpleNamespace(monotonic=lambda: 10.0, time=time, sleep=lambda _: None)
            with (patch("steam_pose_bridge.time", bridge_clock),
                  patch("steam_pose_bridge.PoseFile", LeavingReceiver)):
                run_bridge(data, Link(), b"G", "leon", "claire", stop=stop, lobby_enabled=True)

        self.assertEqual(departures, [7])

    def test_bridges_export_opposite_poses_and_clear_on_disconnect(self):
        import json
        from pathlib import Path
        from queue import Empty, Queue
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from time import monotonic, sleep, time
        from unittest.mock import patch

        from steam_pose_bridge import _encode, run_bridge
        from lobby_control import submit
        from lobby_sync import write_json

        connected = Event()
        connected.set()
        membership = 1
        stops = [Event(), Event()]
        invitations = Queue()
        drop_host_event = Event()
        dropped = Event()

        class Link:
            def __init__(self, role, inbox, outbox):
                self.identity = role
                self.inbox, self.outbox = inbox, outbox
                self.role = self.epoch = None

            def receive(self):
                self.role = self.identity if connected.is_set() else None
                self.epoch = membership.to_bytes(8, "little") if self.role else None
                try:
                    return self.inbox.get_nowait() if self.role else None
                except Empty:
                    return None

            def send(self, value):
                if self.identity == b"H" and drop_host_event.is_set() and value["type"] == "event":
                    drop_host_event.clear()
                    dropped.set()
                    return
                self.outbox.put(_encode(value))

            def invite_dialog(self):
                invitations.put(self.identity)

            def lobby_status(self):
                if not connected.is_set():
                    return "idle"
                return "owned" if self.identity == b"H" else "joined"

            def membership_revision(self):
                return membership if connected.is_set() else None

            def leave_lobby(self, revision):
                if revision != self.membership_revision():
                    raise ValueError("Steam lobby membership changed")
                connected.clear()

        with (TemporaryDirectory() as temp,
              patch("steam_pose_bridge.PEER_TIMEOUT", 0.4),
              patch("steam_pose_bridge.RETRY_INTERVAL", 0.1)):
            directories = [Path(temp) / name for name in ("host", "guest")]
            leon_motion = {"bank": 1, "id": 160,
                           "name": "pl00_0160_OFF_Gazing_Idle_F_Loop",
                           "frame": 550.0, "end_frame": 1100.0}
            claire_motion = {"bank": 1000, "id": 230,
                             "name": "pl00_0230_KFF_Jog_LCycle_Loop",
                             "frame": 30.0, "end_frame": 80.0}
            a, b = Queue(), Queue()
            errors = Queue()
            threads = []
            def run(path, link, kind, halt):
                try:
                    run_bridge(path, link, kind, "leon", "claire", stop=halt,
                               lobby_enabled=True, lobby_config={"save_slot": "slot-1"})
                except Exception as exc:
                    errors.put(exc)

            for index, (directory, role, inbox, outbox, position) in enumerate(zip(
                    directories, (b"H", b"G"), (a, b), (b, a), ([1, 2, 3], [4, 5, 6]))):
                directory.mkdir()
                local = {**sample(1, position), "source": "re2", "schema": 1,
                         "available": True, "observed_at": int(time())}
                local["motion"] = leon_motion if role == b"H" else claire_motion
                (directory / "re2_coop_observer.json").write_text(json.dumps(local), encoding="utf-8")

                thread = Thread(target=run, args=(directory, Link(role, inbox, outbox),
                                                  role, stops[index]))
                thread.start()
                threads.append(thread)

            def renew_sources():
                for directory in directories:
                    source = directory / "re2_coop_observer.json"
                    current = json.loads(source.read_text(encoding="utf-8"))
                    current.update(sequence=current["sequence"] + 1, observed_at=int(time()))
                    write_json(source, current)

            def wait_for_lobby(directory, predicate):
                deadline = monotonic() + 4
                while monotonic() < deadline:
                    if not errors.empty():
                        raise errors.get()
                    try:
                        status = json.loads((directory / "re2_coop_lobby.json").read_text(encoding="utf-8"))
                        if status["connected"] and status["lobby"] and predicate(status["lobby"]):
                            return status["lobby"]
                    except (FileNotFoundError, PermissionError):
                        pass
                    sleep(0.02)
                self.fail("lobby state did not reach the other bridge")

            def wait_for_pose(directory, expected, *, other_session=None,
                              expected_connected=None, min_sequence=0, refresh_sources=False):
                deadline = monotonic() + 7
                next_refresh = monotonic()
                last_result = None
                while monotonic() < deadline:
                    if refresh_sources and monotonic() >= next_refresh:
                        renew_sources()
                        next_refresh = monotonic() + 0.5
                    if not errors.empty():
                        raise errors.get()
                    try:
                        result = json.loads((directory / "re2_coop_guest_pose.json").read_text(encoding="utf-8"))
                        last_result = result
                        if other_session is not None and result["session_id"] == other_session:
                            sleep(0.02)
                            continue
                        if (expected_connected is not None
                                and result["connected"] != expected_connected):
                            sleep(0.02)
                            continue
                        if (expected is None and result["pose"] is None
                                and (result["sequence"] or 0) >= min_sequence):
                            return result
                        if result["pose"] and result["pose"]["position"] == expected:
                            return result
                    except (FileNotFoundError, PermissionError):
                        pass
                    sleep(0.02)
                published = {}
                for source in directories:
                    try:
                        published[source.name] = json.loads(
                            (source / "re2_coop_guest_pose.json").read_text(encoding="utf-8"))
                    except (FileNotFoundError, PermissionError):
                        published[source.name] = None
                self.fail(f"did not receive expected pose {expected}; last={last_result!r}; "
                          f"published={published!r}; queued={(a.qsize(), b.qsize())!r}; "
                          f"alive={[thread.is_alive() for thread in threads]!r}")

            try:
                host = wait_for_pose(directories[0], [4, 5, 6])
                guest = wait_for_pose(directories[1], [1, 2, 3])
                self.assertEqual(host["session_id"], guest["session_id"])
                self.assertEqual(host["player_id"], "claire")
                self.assertEqual(guest["player_id"], "leon")
                self.assertEqual(host["pose"]["motion"], claire_motion)
                self.assertEqual(guest["pose"]["motion"], leon_motion)
                wait_for_lobby(directories[1], lambda message: message["data"]["save_slot"] == "slot-1")
                with self.assertRaisesRegex(ValueError, "only the host"):
                    submit(directories[1], "invite", True)
                submit(directories[0], "invite", True)
                self.assertEqual(invitations.get(timeout=2), b"H")
                with self.assertRaisesRegex(ValueError, "only the host"):
                    submit(directories[1], "configure", {"save_slot": "forged", "settings": {}})
                submit(directories[0], "configure", {"save_slot": "slot-2",
                                                      "settings": {"difficulty": "standard"}})
                choices = wait_for_lobby(directories[1], lambda message: message["data"]["save_slot"] == "slot-2")
                self.assertEqual(choices["data"]["settings"], {"difficulty": "standard"})
                submit(directories[0], "ready", True)
                submit(directories[1], "ready", True)
                for directory in directories:
                    wait_for_lobby(directory, lambda message: all(message["data"]["ready"].values()))
                original_session = guest["session_id"]
                # Neither simulated renderer writes another pose. The bridges still
                # exchange heartbeats, and pose expiry must leave player readiness intact.
                for directory in directories:
                    wait_for_pose(directory, None, expected_connected=True)
                    state = wait_for_lobby(directory, lambda message: message["session_id"] == original_session)
                    self.assertEqual(state["data"]["revision"], choices["data"]["revision"])
                    self.assertTrue(all(state["data"]["ready"].values()))
                # Force a real sequence gap through both running bridges while the
                # native peer epoch, Steam membership and host session stay the same.
                drop_host_event.set()
                renew_sources()
                self.assertTrue(dropped.wait(2), "the host should publish the first renewed pose")
                renew_sources()
                wait_for_lobby(directories[1], lambda message: message["session_id"] == original_session
                               and not any(message["data"]["ready"].values()))
                status = json.loads((directories[1] / "re2_coop_lobby.json").read_bytes())
                self.assertEqual(status["last_link_loss"]["reason"], "guest_resync_required")
                self.assertEqual(status["last_link_loss"]["role"], "G")
                stops[0].set()
                threads[0].join(2)
                self.assertFalse(threads[0].is_alive())
                self.assertIsNone(wait_for_pose(directories[1], None,
                                                expected_connected=False)["pose"])
                # Keep the guest waiting through two more peer timeouts before restarting the host.
                sleep(0.9)
                replacement_stop = Event()
                stops.append(replacement_stop)
                replacement = Thread(target=run, args=(directories[0], Link(b"H", a, b),
                                                       b"H", replacement_stop))
                replacement.start()
                threads.append(replacement)
                renewed = wait_for_pose(directories[1], [1, 2, 3],
                                        other_session=original_session,
                                        refresh_sources=True)
                self.assertNotEqual(renewed["session_id"], original_session)
                self.assertEqual(renewed["pose"]["motion"], leon_motion)
                lobby = wait_for_lobby(directories[1], lambda message: message["session_id"] == renewed["session_id"])
                self.assertFalse(any(lobby["data"]["ready"].values()))
                last_pose_sequence = renewed["sequence"]
                for directory in directories:
                    wait_for_pose(directory, None, expected_connected=True,
                                  min_sequence=last_pose_sequence + 2)
                submit(directories[1], "leave", True)
                for directory in directories:
                    self.assertIsNone(wait_for_pose(directory, None,
                                                    expected_connected=False)["pose"])
                connected.set()
                rejoined = wait_for_pose(directories[1], [1, 2, 3], refresh_sources=True)
                wait_for_lobby(directories[1], lambda message: message["session_id"] == rejoined["session_id"])
                guest_status = json.loads((directories[1] / "re2_coop_lobby.json").read_bytes())
                self.assertEqual(guest_status["last_link_loss"]["reason"], "local_leave")
                self.assertGreater(guest_status["last_link_loss"]["at"], 0)
                self.assertEqual(rejoined["session_id"], renewed["session_id"])
                submit(directories[1], "leave", True)
                for directory in directories:
                    wait_for_pose(directory, None, expected_connected=False)
                membership += 1
                connected.set()
                new_guest = wait_for_pose(directories[1], [1, 2, 3],
                                          other_session=renewed["session_id"], refresh_sources=True)
                latest = wait_for_lobby(directories[1], lambda message: message["session_id"] == new_guest["session_id"])
                self.assertFalse(any(latest["data"]["ready"].values()))
            finally:
                for halt in stops:
                    halt.set()
                for thread in threads:
                    thread.join(2)
                    self.assertFalse(thread.is_alive())
