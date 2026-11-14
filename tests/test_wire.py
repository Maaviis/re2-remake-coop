import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WireTests(unittest.TestCase):
    def test_two_processes_and_reconnect(self):
        self._exercise_reconnect([])

    def test_two_versioned_processes_and_reconnect(self):
        self._exercise_reconnect(["--protocol-version", "1"])

    def _exercise_reconnect(self, options):
        command = [sys.executable, "-u", str(ROOT / "wire.py")]
        host = subprocess.Popen([*command, "host", *options],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        listener = None
        try:
            port = int(host.stdout.readline().strip())
            client_command = [*command, "client", "--port", str(port), *options]
            listener = subprocess.Popen([*client_command, "--listen", "--events", "2"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(listener.stdout.readline().strip(), "READY")
            proposal = json.dumps({"kind": "enemy", "target": "zombie-1",
                                   "value": {"health": 0, "dead": True}})
            first = subprocess.run([*client_command, "--propose", proposal],
                                   check=True, capture_output=True, text=True, timeout=10)
            next_proposal = json.dumps({"kind": "door", "target": "rpd-hall", "value": "open"})
            next_event = subprocess.run([*client_command, "--propose", next_proposal],
                                        check=True, capture_output=True, text=True, timeout=10)
            listener_output, listener_error = listener.communicate(timeout=10)
            self.assertEqual(listener.returncode, 0, listener_error)
            self.assertEqual(json.loads(next_event.stdout), json.loads(listener_output))
            self.assertEqual(json.loads(first.stdout)["sequence"], 1)
            second = subprocess.run(client_command, check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(json.loads(next_event.stdout), json.loads(second.stdout))
            self.assertTrue(json.loads(second.stdout)["state"]["enemies"]["zombie-1"]["dead"])
            self.assertEqual(json.loads(second.stdout)["state"]["doors"]["rpd-hall"], "open")
        finally:
            if listener is not None and listener.poll() is None:
                listener.terminate()
                listener.communicate(timeout=5)
            host.terminate()
            host.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()

