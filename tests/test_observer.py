import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observer import forward_sample, read_sample
from wire import Server


class ObserverTests(unittest.TestCase):
    def test_reframework_sample_reaches_host(self):
        sample = {"schema": 1, "source": "re2", "run_id": "game-run-1", "tdb": 70, "sequence": 3,
                  "position": [1.0, 2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]}
        with patch.object(Path, "read_text", return_value=json.dumps(sample)):
            parsed = read_sample(Path("observer.json"))
        with Server(("127.0.0.1", 0)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
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
            finally:
                server.shutdown()
                thread.join(timeout=2)

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

