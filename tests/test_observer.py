from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observer import forward_sample, read_sample
from sync_model import Host, Replica
from wire import Server, receive, send


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = {"schema": 1, "source": "re2", "run_id": "game-run-1", "tdb": 70,
          "sequence": 3, "position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]}


@contextmanager
def running_server(protocol_version=0):
    with Server(("127.0.0.1", 0), protocol_version=protocol_version) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


class ObserverTests(unittest.TestCase):
    def test_matching_event_received_after_deadline_is_not_acknowledged(self):
        host, replica = Host(), Replica()
        replica.restore(host.snapshot())
        value = {"position": SAMPLE["position"], "rotation": SAMPLE["rotation"], "tdb": 70,
                 "observer_sequence": SAMPLE["sequence"], "observer_run_id": SAMPLE["run_id"]}
        event = host.emit("player", "claire", value)
        with (patch("observer.socket.create_connection"),
              patch("observer.join_replica", return_value=replica),
              patch("observer.receive", return_value={"type": "event", "data": event}),
              patch("observer.time.monotonic", side_effect=[0, 0, 6])):
            with self.assertRaisesRegex(TimeoutError, "did not acknowledge"):
                forward_sample(0, "claire", SAMPLE)

    def test_waits_for_its_own_verified_event_after_unrelated_broadcast(self):
        for version in (0, 1):
            with self.subTest(version=version):
                self._exercise_interleaved_reply(version)

    def _exercise_interleaved_reply(self, version):
        host = Host()
        peer, client_socket = socket.socketpair()
        with peer, client_socket, ThreadPoolExecutor(max_workers=1) as executor:
            peer.settimeout(2)

            def serve():
                with peer.makefile("rwb") as stream:
                    if version:
                        send(stream, {"type": "hello"}, protocol_version=version)
                        self.assertEqual(receive(stream, protocol_version=version)["type"], "hello")
                    send(stream, {"type": "snapshot", "data": host.snapshot()},
                         protocol_version=version)
                    request = receive(stream, protocol_version=version)
                    unrelated = host.emit("player", "leon", request["value"])
                    older = host.emit("player", "claire", {**request["value"], "observer_sequence": 2})
                    numeric_alias = host.emit("player", "claire", {
                        **request["value"], "position": [1, 2, 3],
                    })
                    own = host.emit("player", "claire", request["value"])
                    for event in (unrelated, older, numeric_alias, own):
                        send(stream, {"type": "event", "data": event}, protocol_version=version)

            host_task = executor.submit(serve)
            with patch("observer.socket.create_connection", return_value=client_socket):
                acknowledged = forward_sample(0, "claire", SAMPLE, protocol_version=version)
            host_task.result(timeout=3)
            self.assertEqual(acknowledged["target"], "claire")
            self.assertEqual(acknowledged["sequence"], 4)

    def test_v1_file_sample_reaches_a_connected_guest_process(self):
        with running_server(1) as server, tempfile.TemporaryDirectory() as work:
            port = str(server.server_address[1])
            guest = subprocess.Popen(
                [sys.executable, str(ROOT / "wire.py"), "client", "--port", port,
                 "--listen", "--events", "2", "--protocol-version", "1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                # The guest emits READY only after receiving and verifying its initial snapshot.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    ready = executor.submit(guest.stdout.readline)
                    try:
                        self.assertEqual(ready.result(timeout=5).strip(), "READY")
                    finally:
                        if not ready.done():
                            guest.terminate()

                sample_path = Path(work) / "re2_coop_observer.json"
                rotated = {**SAMPLE, "sequence": 4, "rotation": [0.0, 0.6, 0.0, 0.8]}
                for expected_sequence, sample in enumerate((SAMPLE, rotated), 1):
                    sample_path.write_text(json.dumps(sample), encoding="utf-8")
                    run = subprocess.run(
                        [sys.executable, str(ROOT / "observer.py"), "--file", str(sample_path),
                         "--port", port, "--player-id", "claire", "--protocol-version", "1", "--once"],
                        capture_output=True, text=True, timeout=8,
                    )
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(json.loads(run.stdout)["host_sequence"], expected_sequence)

                output, error = guest.communicate(timeout=5)
                self.assertEqual(guest.returncode, 0, error)
                snapshot = json.loads(output)
                self.assertEqual(snapshot, server.host_state.snapshot())
                self.assertEqual(snapshot["state"]["players"]["claire"]["position"], rotated["position"])
                self.assertEqual(snapshot["state"]["players"]["claire"]["rotation"], rotated["rotation"])
            finally:
                if guest.poll() is None:
                    guest.terminate()
                guest.communicate(timeout=5)

    def test_reframework_sample_reaches_host(self):
        sample = {"schema": 1, "source": "re2", "run_id": "game-run-1", "tdb": 70, "sequence": 3,
                  "position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]}
        with patch.object(Path, "read_text", return_value=json.dumps(sample)):
            parsed = read_sample(Path("observer.json"))
        with running_server() as server:
            event = forward_sample(server.server_address[1], "claire", parsed)
            self.assertEqual(event["sequence"], 1)
            self.assertEqual(server.host_state.state["players"]["claire"]["position"],
                             [1.0, 2.0, 3.0])
            self.assertEqual(server.host_state.state["players"]["claire"]["observer_run_id"],
                             "game-run-1")
            turned = {**parsed, "sequence": 4, "rotation": [0.0, 0.6, 0.0, 0.8]}
            event = forward_sample(server.server_address[1], "claire", turned)
            self.assertEqual(event["sequence"], 2)
            player = server.host_state.state["players"]["claire"]
            self.assertEqual(player["position"], [1.0, 2.0, 3.0])
            self.assertEqual(player["rotation"], [0.0, 0.6, 0.0, 0.8])

    def test_invalid_position_is_rejected(self):
        sample = {"schema": 1, "source": "re2", "run_id": "game-run-1", "sequence": 1,
                  "position": [float("nan"), 0, 0], "rotation": [0, 0, 0, 1]}
        with patch.object(Path, "read_text", return_value=json.dumps(sample)):
            with self.assertRaisesRegex(ValueError, "invalid position"):
                read_sample(Path("observer.json"))

    def test_missing_run_id_is_rejected(self):
        sample = {"schema": 1, "source": "re2", "sequence": 1,
                  "position": [0, 0, 0], "rotation": [0, 0, 0, 1]}
        with patch.object(Path, "read_text", return_value=json.dumps(sample)):
            with self.assertRaisesRegex(ValueError, "run id required"):
                read_sample(Path("observer.json"))


if __name__ == "__main__":
    unittest.main()
