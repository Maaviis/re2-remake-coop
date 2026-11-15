import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from observer import forward_sample, run_observer
from wire import Server


ROOT = Path(__file__).resolve().parents[1]
OBSERVATION = "re2_coop_observer.json"
REMOTE_POSE = "re2_coop_guest_pose.json"
LEON = {"position": [1, 2, 3], "rotation": [0, 0, 0, 1]}
CLAIRE = {"position": [4, 5, 6], "rotation": [0, 0.6, 0, 0.8]}


def bridge_command(data, port, local_id, remote_id):
    return [
        sys.executable, str(ROOT / "pose_bridge.py"), "--data", str(data), "--port", str(port),
        "--local-player-id", local_id, "--remote-player-id", remote_id,
    ]


def publish(data, player, sequence, pose):
    sample = {"schema": 1, "source": "re2", "run_id": player, "sequence": sequence,
              "tdb": 70, "observed_at": int(time.time()), "available": pose is not None}
    if pose is not None:
        sample.update(pose)
    temporary = data / "pending.json"
    temporary.write_text(json.dumps(sample), encoding="utf-8")
    deadline = time.monotonic() + 5
    while True:
        try:
            os.replace(temporary, data / OBSERVATION)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def wait_for_file(data, expected, *, connected=True, after=-1, process=None):
    path = data / REMOTE_POSE
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError):
            pass
        else:
            if (doc["connected"] is connected and doc["pose"] == expected
                    and (doc["sequence"] or 0) > after):
                return doc
        if process is not None and process.poll() is not None:
            raise AssertionError(f"bridge stopped before publishing: {process.stderr.read()}")
        time.sleep(0.02)
    raise AssertionError(f"expected pose file at {path}")


class PoseBridgeTests(unittest.TestCase):
    def test_observer_retries_a_transient_failure_in_the_verified_session(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            publish(data, "leon", 1, LEON)
            stop = Event()

            def forward(*args, **kwargs):
                if sending.call_count == 1:
                    raise ConnectionResetError("forwarder connection reset")
                stop.set()
                return {"sequence": 1}

            with patch("observer.forward_sample", side_effect=forward) as sending:
                run_observer(data / OBSERVATION, 45678, "leon", protocol_version=1,
                             stop=stop, active_session=lambda: "host-session", reconnect_attempts=1)
            self.assertEqual(sending.call_count, 2)
            first, second = sending.call_args_list
            self.assertEqual(first, second)
            self.assertEqual(second.kwargs["expected_session"], "host-session")

    def test_observer_does_not_publish_to_a_replacement_session(self):
        with Server(("127.0.0.1", 0), protocol_version=1) as host:
            serving = Thread(target=host.serve_forever, kwargs={"poll_interval": 0.02})
            serving.start()
            try:
                sample = {**LEON, "sequence": 1, "run_id": "leon", "tdb": 70}
                with self.assertRaisesRegex(ValueError, "session mismatch"):
                    forward_sample(host.server_address[1], "leon", sample, protocol_version=1,
                                   expected_session="prior-session")
                self.assertEqual(host.host_state.sequence, 0)
                first = forward_sample(host.server_address[1], "leon", sample, protocol_version=1,
                                       expected_session=host.host_state.session_id)
                retried = forward_sample(host.server_address[1], "leon", sample, protocol_version=1,
                                         expected_session=host.host_state.session_id)
                self.assertEqual(first["sequence"], retried["sequence"])
                self.assertEqual(host.host_state.sequence, 1)
            finally:
                host.shutdown()
                serving.join(timeout=3)

    def test_rejects_the_same_local_and_remote_player(self):
        with TemporaryDirectory() as temporary:
            data = Path(temporary)
            result = subprocess.run(bridge_command(data, 45678, "leon", "leon"),
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("must be different", result.stderr)
            self.assertFalse((data / REMOTE_POSE).exists())

    def test_two_bridges_apply_only_the_other_player_and_clear_on_observer_failure(self):
        with TemporaryDirectory() as temporary, Server(("127.0.0.1", 0), protocol_version=1) as host:
            port = host.server_address[1]
            serving = Thread(target=host.serve_forever, kwargs={"poll_interval": 0.02})
            serving.start()
            leon, claire = Path(temporary) / "A", Path(temporary) / "B"
            processes = []
            try:
                for data, local_id, remote_id in ((leon, "leon", "claire"), (claire, "claire", "leon")):
                    data.mkdir()
                    process = subprocess.Popen(bridge_command(data, port, local_id, remote_id),
                                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                    processes.append(process)
                    wait_for_file(data, None, process=process)
                # A nonempty sentinel must still lock byte zero on Windows.
                with (leon / "re2_coop_pose_bridge.lock").open("r+b") as lock_file:
                    lock_file.seek(1)
                    lock_file.write(b"x")
                duplicate = subprocess.run(bridge_command(leon, port, "leon", "claire"),
                                           capture_output=True, text=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn("already running", duplicate.stderr)

                publish(leon, "leon", 1, LEON)
                b = wait_for_file(claire, LEON, process=processes[1])
                self.assertEqual(b["player_id"], "leon")
                wait_for_file(leon, None, after=0, process=processes[0])
                publish(claire, "claire", 1, CLAIRE)
                a = wait_for_file(leon, CLAIRE, process=processes[0])
                self.assertEqual(a["player_id"], "claire")
                self.assertEqual(a["session_id"], b["session_id"])

                publish(leon, "leon", 2, None)
                wait_for_file(claire, None, after=b["sequence"], process=processes[1])
                wait_for_file(leon, CLAIRE, after=a["sequence"], process=processes[0])

                publish(leon, "new-script-run", 1, LEON)
                _, stderr = processes[0].communicate(timeout=6)
                self.assertNotEqual(processes[0].returncode, 0)
                self.assertIn("observer", stderr)
                wait_for_file(leon, None, connected=False)
                self.assertIsNone(processes[1].poll())

                # Trigger orderly cleanup of the second supervisor, too.
                publish(claire, "new-script-run", 1, CLAIRE)
                processes[1].communicate(timeout=6)
                wait_for_file(claire, None, connected=False)
            finally:
                # Closing the listening host also interrupts the two transport legs on failure.
                host.shutdown()
                serving.join(timeout=3)
                with host.state_lock:
                    clients = tuple(host.clients)
                for client in clients:
                    try:
                        client.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                for process in processes:
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
