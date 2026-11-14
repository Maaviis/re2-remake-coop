from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch

from sync_model import Host
from wire import follow_replica, receive, send


FIRST = {"position": [1, 2, 3], "rotation": [0, 0, 0, 1]}
SECOND = {"position": [4, 5, 6], "rotation": [0, 0.6, 0, 0.8]}
ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def local_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        yield listener


def send_snapshot(connection, snapshot):
    connection.settimeout(3)
    with connection.makefile("rwb") as stream:
        send(stream, {"type": "hello"}, protocol_version=1)
        if receive(stream, protocol_version=1)["type"] != "hello":
            raise AssertionError("expected a v1 guest hello")
        send(stream, {"type": "snapshot", "data": snapshot}, protocol_version=1)


def wait_for_pose(path, predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            pose = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError):
            # Windows can reject a read briefly during atomic replacement.
            pass
        else:
            if predicate(pose):
                return pose
        time.sleep(0.01)
    raise AssertionError("guest did not publish the expected pose file")


class GuestReconnectTests(unittest.TestCase):
    def test_tcp_reset_hides_pose_and_rejoin_restores_missed_host_state(self):
        host = Host()
        host.emit("player", "claire", FIRST)
        with (local_listener() as listener, ThreadPoolExecutor(max_workers=1) as pool,
              tempfile.TemporaryDirectory() as work):
            first_ready, disconnected, rejoined = Event(), Event(), Event()

            def serve():
                first, _ = listener.accept()
                with first:
                    send_snapshot(first, host.snapshot())
                    # Wait until the test has consumed the first snapshot before resetting.
                    self.assertTrue(first_ready.wait(5))
                    host.emit("player", "claire", SECOND)
                    linger_format = "HH" if sys.platform == "win32" else "ii"
                    first.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                     struct.pack(linger_format, 1, 0))
                second, _ = listener.accept()
                with second:
                    self.assertTrue(disconnected.wait(5))
                    send_snapshot(second, host.snapshot())
                    self.assertTrue(rejoined.wait(5))
            serving = pool.submit(serve)
            path = Path(work) / "pose.json"
            guest = subprocess.Popen(
                [sys.executable, str(ROOT / "guest_pose.py"), "--port", str(listener.getsockname()[1]),
                 "--output", str(path), "--remote-player-id", "claire", "--reconnect-attempts", "1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                initial = wait_for_pose(path, lambda pose: pose["connected"])
                self.assertEqual(initial["pose"], FIRST)
                first_ready.set()
                hidden = wait_for_pose(path, lambda pose: not pose["connected"])
                self.assertIsNone(hidden["pose"])
                disconnected.set()
                recovered = wait_for_pose(path, lambda pose: pose["connected"])
                self.assertEqual(recovered["pose"], SECOND)
                self.assertEqual(recovered["session_id"], host.session_id)
                self.assertEqual(recovered["sequence"], 2)
                rejoined.set()
                stdout, stderr = guest.communicate(timeout=5)
                self.assertEqual(guest.returncode, 0, stderr)
                self.assertEqual(stdout.splitlines(), ["READY", "READY"])
                self.assertFalse(json.loads(path.read_text(encoding="utf-8"))["connected"])
            finally:
                if guest.poll() is None:
                    guest.kill()
                    guest.communicate(timeout=5)
                first_ready.set()
                disconnected.set()
                rejoined.set()
            serving.result(timeout=3)

    def test_rejects_rejoin_with_wrong_session_stale_or_conflicting_snapshot(self):
        for failure, expected in (("session", "session mismatch"), ("stale", "stale snapshot"),
                                  ("conflict", "divergent snapshot")):
            with self.subTest(failure=failure), local_listener() as listener, ThreadPoolExecutor() as pool:
                host = Host(session_id="original")
                stale = host.snapshot()
                host.emit("player", "claire", FIRST)
                different = Host(session_id="original")
                different.emit("player", "claire", SECOND)
                bad = {"session": Host(session_id="other").snapshot(),
                       "stale": stale, "conflict": different.snapshot()}[failure]

                def serve():
                    for snapshot in (host.snapshot(), bad):
                        connection, _ = listener.accept()
                        with connection:
                            send_snapshot(connection, snapshot)

                serving = pool.submit(serve)
                with closing(follow_replica(listener.getsockname()[1], reconnect_attempts=1)) as updates:
                    replica = next(updates)
                    self.assertEqual(replica.snapshot(), host.snapshot())
                    self.assertIsNone(next(updates))
                    with self.assertRaisesRegex(ValueError, expected):
                        next(updates)
                    self.assertEqual(replica.snapshot(), host.snapshot())
                serving.result(timeout=3)

    def test_retry_attempts_are_bounded(self):
        with (patch("wire.RECONNECT_DELAY", 0),
              patch("wire.socket.create_connection", side_effect=ConnectionRefusedError) as connect):
            with self.assertRaises(ConnectionRefusedError):
                list(follow_replica(45678, reconnect_attempts=2))
        self.assertEqual(connect.call_count, 3)

    def test_recovers_from_digest_mismatch_and_sequence_gap(self):
        for failure in ("digest", "gap"):
            with self.subTest(failure=failure), local_listener() as listener, ThreadPoolExecutor() as pool:
                host = Host()
                first = host.snapshot()
                host.emit("door", "hall", "open")
                event = host.emit("player", "claire", SECOND)
                if failure == "digest":
                    event = {**event, "sequence": 1, "digest": "0" * 64}

                def serve():
                    connection, _ = listener.accept()
                    with connection, connection.makefile("rwb") as stream:
                        connection.settimeout(3)
                        send(stream, {"type": "hello"}, protocol_version=1)
                        self.assertEqual(receive(stream, protocol_version=1)["type"], "hello")
                        send(stream, {"type": "snapshot", "data": first}, protocol_version=1)
                        send(stream, {"type": "event", "data": event}, protocol_version=1)
                        self.assertEqual(stream.read(1), b"")
                    connection, _ = listener.accept()
                    with connection:
                        send_snapshot(connection, host.snapshot())

                serving = pool.submit(serve)
                with closing(follow_replica(listener.getsockname()[1], reconnect_attempts=1)) as updates:
                    replica = next(updates)
                    self.assertEqual(replica.snapshot(), first)
                    self.assertIsNone(next(updates))
                    self.assertEqual(replica.snapshot(), first)
                    self.assertEqual(next(updates).snapshot(), host.snapshot())
                serving.result(timeout=3)

    def test_rejoins_after_peer_closes_mid_frame(self):
        with local_listener() as listener, ThreadPoolExecutor(max_workers=1) as pool:
            host = Host()

            def serve():
                connection, _ = listener.accept()
                with connection:
                    send_snapshot(connection, host.snapshot())
                    connection.sendall(b'{"version":1,"type":"event","data":')
                    connection.shutdown(socket.SHUT_WR)
                host.emit("player", "claire", SECOND)
                connection, _ = listener.accept()
                with connection:
                    send_snapshot(connection, host.snapshot())

            serving = pool.submit(serve)
            with closing(follow_replica(listener.getsockname()[1], reconnect_attempts=1)) as updates:
                self.assertEqual(next(updates).sequence, 0)
                self.assertIsNone(next(updates))
                self.assertEqual(next(updates).snapshot(), host.snapshot())
            serving.result(timeout=3)


if __name__ == "__main__":
    unittest.main()
