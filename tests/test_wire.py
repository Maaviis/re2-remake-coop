import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WireTests(unittest.TestCase):
    def test_two_processes_and_reconnect(self):
        host = subprocess.Popen([sys.executable, "-u", str(ROOT / "wire.py"), "host"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        listener = None
        try:
            port = int(host.stdout.readline().strip())
            listener = subprocess.Popen([sys.executable, "-u", str(ROOT / "wire.py"),
                                         "client", "--port", str(port), "--listen"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(listener.stdout.readline().strip(), "READY")

            invalid = json.dumps({"kind": "player", "target": "leon",
                                  "value": {"position": [float("nan"), 0, 0]}})
            rejected = subprocess.run([sys.executable, str(ROOT / "wire.py"), "client",
                                       "--port", str(port), "--propose", invalid],
                                      capture_output=True, text=True, timeout=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Out of range float values", rejected.stderr)

            proposal = json.dumps({"kind": "enemy", "target": "zombie-1",
                                   "value": {"health": 0, "dead": True}})
            first = subprocess.run([sys.executable, str(ROOT / "wire.py"), "client",
                                    "--port", str(port), "--propose", proposal],
                                   check=True, capture_output=True, text=True, timeout=10)
            listener_output, listener_error = listener.communicate(timeout=10)
            self.assertEqual(listener.returncode, 0, listener_error)
            self.assertEqual(json.loads(first.stdout), json.loads(listener_output))
            second = subprocess.run([sys.executable, str(ROOT / "wire.py"), "client",
                                     "--port", str(port)], check=True, capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
            self.assertEqual(json.loads(second.stdout)["sequence"], 1)
            self.assertTrue(json.loads(second.stdout)["state"]["enemies"]["zombie-1"]["dead"])
        finally:
            if listener is not None and listener.poll() is None:
                listener.terminate()
                listener.communicate(timeout=5)
            host.terminate()
            host.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
