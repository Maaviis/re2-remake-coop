from concurrent.futures import ThreadPoolExecutor
import json
from os import replace
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from guest_pose import PoseFile
from observer import forward_sample
from sync_model import Host, Replica
from wire import Server, client, receive, send


POSE = {"position": [1, 2, 3], "rotation": [0, 0.6, 0, 0.8]}


class GuestPoseTests(unittest.TestCase):
    def test_verified_motion_is_exported_with_remote_pose(self):
        motion = {"bank": 1, "id": 160, "name": "pl00_0160_OFF_Gazing_Idle_F_Loop",
                  "frame": 10.5, "end_frame": 1100.0}
        host = Host()
        host.emit("player", "leon", {**POSE, "motion": motion})
        replica = Replica()
        replica.restore(host.snapshot())
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "pose.json"
            with PoseFile(path, "leon") as output:
                output.update(replica)
                self.assertEqual(read_pose(path)["pose"]["motion"], motion)
                replica.apply(host.emit("player", "leon", {**POSE, "motion": {**motion, "frame": 2000}}))
                output.update(replica)
                self.assertNotIn("motion", read_pose(path)["pose"])

    def test_pose_expires_without_new_observations_even_when_file_lease_is_renewed(self):
        host = Host()
        host.emit("player", "claire", {**POSE, "observed_at": 100})
        replica = Replica()
        replica.restore(host.snapshot())
        with (tempfile.TemporaryDirectory() as work,
              patch("guest_pose.time.time", return_value=100) as now,
              patch("guest_pose.time.monotonic", return_value=50) as ticks,
              patch("guest_pose.HEARTBEAT_SECONDS", 60)):
            path = Path(work) / "pose.json"
            with PoseFile(path, "claire") as output:
                output.update(replica)
                self.assertEqual(read_pose(path)["pose"], POSE)
                now.return_value = 106
                # Exercise the same write used for a lease renewal or later game event.
                output._write()
                data = read_pose(path)
                self.assertEqual(data["written_at"], 106)
                self.assertTrue(data["connected"])
                self.assertIsNone(data["pose"])
                now.return_value = 104
                ticks.return_value = 56
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"], "clock rollback revived an old observation")
                now.return_value = 106
                replica.apply(host.emit("player", "claire", {**POSE, "observed_at": 106}))
                output.update(replica)
                self.assertEqual(read_pose(path)["pose"], POSE)

    def test_steam_pose_lease_uses_local_receipt_clock(self):
        host = Host()
        source = {**POSE, "observed_at": 100, "observer_run_id": "remote",
                  "observer_sequence": 1}
        host.emit("player", "claire", source)
        replica = Replica()
        replica.restore(host.snapshot())
        with (tempfile.TemporaryDirectory() as work,
              patch("guest_pose.time.time", return_value=1000) as now,
              patch("guest_pose.time.monotonic", return_value=50) as ticks,
              patch("guest_pose.HEARTBEAT_SECONDS", 60)):
            path = Path(work) / "pose.json"
            with PoseFile(path, "claire", local_clock_lease=True) as output:
                output.update(replica)
                data = read_pose(path)
                self.assertEqual(data["pose"], POSE)
                self.assertEqual(data["observed_at"], 1000)
                now.return_value, ticks.return_value = 1006, 56
                output._write()
                self.assertIsNone(read_pose(path)["pose"])
                now.return_value, ticks.return_value = 1000, 57
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"], "old source event cannot renew a lease")
                replica.apply(host.emit("player", "claire", {**source, "observer_sequence": 2}))
                ticks.return_value = 58
                output.update(replica)
                self.assertEqual(read_pose(path)["pose"], POSE)
                replica.apply(host.emit("player", "claire", {**POSE, "observed_at": 100}))
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"], "missing observer identity has no local lease")

    def test_retries_temporary_file_sharing_conflict(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "pose.json"
            def replace_after_conflict(source, destination):
                if replacing.call_count == 2:
                    raise PermissionError("file briefly open in REFramework")
                replace(source, destination)

            host = Host()
            host.emit("player", "claire", POSE)
            replica = Replica()
            replica.restore(host.snapshot())
            with patch("guest_pose.os.replace", side_effect=replace_after_conflict) as replacing:
                with PoseFile(path, "claire") as output:
                    output.update(replica)
                    self.assertEqual(read_pose(path)["pose"], POSE)
            self.assertFalse(read_pose(path)["connected"])
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_rejects_player_ids_that_cannot_be_rendered(self):
        for player_id in ("", "x" * 129, "claire\nleon"):
            with self.subTest(player_id=player_id), self.assertRaisesRegex(ValueError, "player ID"):
                PoseFile(Path("unused.json"), player_id)

    def test_only_exports_selected_valid_pose_and_clears_on_exit(self):
        host = Host()
        replica = Replica()
        replica.restore(host.snapshot())
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "pose.json"
            with PoseFile(path, "claire") as output:
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"])
                replica.apply(host.emit("player", "leon", POSE))
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"])
                replica.apply(host.emit("player", "claire", POSE))
                output.update(replica)
                self.assertEqual(read_pose(path)["pose"], POSE)
                self.assertEqual(read_pose(path)["sequence"], 2)
                replica.apply(host.emit("player", "claire", {**POSE, "rotation": [0, 0, 0, 0]}))
                output.update(replica)
                self.assertIsNone(read_pose(path)["pose"])
            self.assertFalse(read_pose(path)["connected"])
            self.assertIsNone(read_pose(path)["pose"])

    def test_v1_observer_updates_marker_file_for_a_connected_guest(self):
        now = int(time.time())
        sample = {**POSE, "sequence": 1, "run_id": "test", "tdb": 70,
                  "available": True, "observed_at": now}
        with tempfile.TemporaryDirectory() as work, Server(("127.0.0.1", 0), protocol_version=1) as host:
            path = Path(work) / "pose.json"
            listening = threading.Thread(target=host.serve_forever, kwargs={"poll_interval": 0.02})
            listening.start()
            try:
                port = host.server_address[1]
                with PoseFile(path, "claire") as output, ThreadPoolExecutor() as pool:
                    ready, delivered = threading.Event(), threading.Event()
                    poses = []

                    def publish(replica):
                        output.update(replica)
                        poses.append(read_pose(path))
                        if replica.sequence == 0:
                            ready.set()
                        else:
                            delivered.set()

                    guest = pool.submit(client, port, listen=True, event_count=3,
                                        protocol_version=1, on_state=publish)
                    self.assertTrue(ready.wait(3))
                    forward_sample(port, "claire", sample, protocol_version=1)
                    self.assertTrue(delivered.wait(3))
                    absent = {"sequence": 2, "run_id": "test", "tdb": 70,
                              "available": False, "observed_at": now}
                    forward_sample(port, "claire", absent, protocol_version=1)
                    forward_sample(port, "claire", {**sample, "sequence": 3}, protocol_version=1)
                    guest.result(timeout=3)
                    self.assertEqual(poses[1]["pose"], POSE)
                    self.assertEqual(poses[1]["observed_at"], now)
                    self.assertIsNone(poses[2]["pose"])
                    self.assertTrue(poses[2]["connected"])
                    self.assertEqual(poses[-1]["pose"], POSE)
                    self.assertEqual(poses[-1]["session_id"], host.host_state.session_id)
                    self.assertEqual(poses[-1]["sequence"], 3)
            finally:
                host.shutdown()
                listening.join(timeout=3)
            self.assertFalse(read_pose(path)["connected"])

    def test_corrupt_event_never_reaches_the_pose_file(self):
        host = Host()
        with socket.socket() as listener, ThreadPoolExecutor() as pool:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)

            def serve():
                connection, _ = listener.accept()
                with connection, connection.makefile("rwb") as stream:
                    connection.settimeout(3)
                    send(stream, {"type": "hello"}, protocol_version=1)
                    self.assertEqual(receive(stream, protocol_version=1)["type"], "hello")
                    send(stream, {"type": "snapshot", "data": host.snapshot()}, protocol_version=1)
                    event = host.emit("player", "claire", POSE)
                    event["digest"] = "0" * 64
                    send(stream, {"type": "event", "data": event}, protocol_version=1)

            sending = pool.submit(serve)
            accepted = []
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                client(listener.getsockname()[1], listen=True, event_count=1, protocol_version=1,
                       on_state=lambda state: accepted.append(state.sequence))
            sending.result(timeout=3)
            self.assertEqual(accepted, [0])


def read_pose(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
