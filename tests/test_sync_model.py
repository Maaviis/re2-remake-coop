import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_model import Host, Replica


class SyncModelTests(unittest.TestCase):
    def test_replay_and_reconnect(self):
        host, client = Host(), Replica()
        events = [
            host.emit("player", "leon", {"position": [1, 2, 3], "health": 100}),
            host.emit("enemy", "zombie-1", {"health": 0, "dead": True}),
            host.emit("door", "rpd-hall", "open"),
            host.emit("puzzle", "statue", "solved"),
            host.emit("item", "key-1", {"owner": "claire", "world": False}),
            host.emit("inventory", "claire", ["key-1"]),
            host.emit("flag", "rpd-complete", True),
            host.emit("action", "leon", {"animation": "shoot", "frame": 20}),
            host.emit("damage", "leon", {"amount": 25, "source": "zombie-1"}),
            host.emit("script", "rpd-intro", {"phase": "complete"}),
            host.emit("cutscene", value={"id": "intro", "phase": "playing", "time": 12.5}),
        ]
        for event in events[:3]:
            client.apply(event)
        with self.assertRaisesRegex(ValueError, "sequence gap"):
            client.apply(events[4])
        client.restore(host.snapshot())
        self.assertEqual(client.state, host.state)
        self.assertFalse(client.apply(events[-1]))
        client.apply(host.emit("cutscene", value={"id": "intro", "phase": "ended"}))
        self.assertEqual(client.state, host.state)

    def test_rejects_stale_snapshot(self):
        host = Host()
        old = host.snapshot()
        host.emit("flag", "a", True)
        with self.assertRaisesRegex(ValueError, "stale"):
            host.restore(old)

    def test_rejects_corruption_without_changing_replica(self):
        host, client = Host(), Replica()
        event = host.emit("item", "key", {"owner": "leon"})
        corrupted = deepcopy(event)
        corrupted["value"]["owner"] = "claire"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            client.apply(corrupted)
        self.assertEqual(client.sequence, 0)
        self.assertEqual(client.snapshot()["state"]["items"], {})
        client.apply(event)
        snapshot = host.snapshot()
        snapshot["state"]["items"]["key"]["owner"] = "claire"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            client.restore(snapshot)

    def test_rejects_unverified_event_without_changing_replica(self):
        host, client = Host(), Replica()
        event = host.emit("door", "hall", "open")
        event.pop("digest")
        with self.assertRaisesRegex(ValueError, "digest required"):
            client.apply(event)
        self.assertEqual(client.sequence, 0)
        self.assertEqual(client.state["doors"], {})

    def test_rejects_events_and_snapshots_from_another_session(self):
        first, second, client = Host(), Host(), Replica()
        client.restore(first.snapshot())
        event = second.emit("door", "hall", "open")
        with self.assertRaisesRegex(ValueError, "session mismatch"):
            client.apply(event)
        with self.assertRaisesRegex(ValueError, "session mismatch"):
            client.restore(second.snapshot())
        self.assertEqual(client.session_id, first.session_id)
        self.assertEqual(client.sequence, 0)


if __name__ == "__main__":
    unittest.main()

