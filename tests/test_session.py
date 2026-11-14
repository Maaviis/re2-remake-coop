import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session import Lobby, load_checkpoint, save_checkpoint
from sync_model import Host, Replica


class SessionTests(unittest.TestCase):
    def test_lobby_checkpoint_and_reconnect(self):
        lobby = Lobby("host")
        lobby.select_save("host", "slot-1")
        lobby.configure("host", difficulty="standard", campaign="leon")
        lobby.join("guest")
        lobby.set_ready("host", True, lobby.revision)
        lobby.set_ready("guest", True, lobby.revision)
        lobby.start()
        host = Host()
        host.emit("enemy", "zombie-1", {"health": 0, "dead": True})
        host.emit("cutscene", value={"id": "intro", "phase": "ended"})
        path = Path(__file__).resolve().parents[1] / ("checkpoint-test-" + uuid.uuid4().hex + ".json")
        try:
            save_checkpoint(path, host, lobby)
            restored, slot, settings = load_checkpoint(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(restored.snapshot(), host.snapshot())
        self.assertEqual(slot, "slot-1")
        self.assertEqual(settings["campaign"], "leon")
        guest = Replica()
        guest.restore(restored.snapshot())
        host.emit("flag", "next-scene", True)
        host.emit("door", "hall", "open")
        with self.assertRaisesRegex(ValueError, "sequence gap"):
            guest.apply({"session_id": host.session_id, "sequence": 4,
                         "kind": "door", "target": "hall", "value": "open"})
        guest.restore(host.snapshot())
        self.assertEqual(guest.state, host.state)

    def test_readiness_resets_after_change(self):
        lobby = Lobby("host")
        lobby.select_save("host", "slot-1")
        lobby.join("guest")
        lobby.set_ready("host", True, lobby.revision)
        lobby.set_ready("guest", True, lobby.revision)
        lobby.configure("host", difficulty="hardcore")
        with self.assertRaisesRegex(ValueError, "not ready"):
            lobby.start()

    def test_host_authority_and_stale_readiness(self):
        lobby = Lobby("host")
        with self.assertRaisesRegex(ValueError, "only the host"):
            lobby.select_save("guest", "slot-1")
        lobby.select_save("host", "slot-1")
        lobby.join("guest")
        revision = lobby.revision
        lobby.configure("host", difficulty="standard")
        with self.assertRaisesRegex(ValueError, "only the host"):
            lobby.configure("guest", difficulty="hardcore")
        with self.assertRaisesRegex(ValueError, "revision"):
            lobby.set_ready("guest", True, revision)
        lobby.set_ready("host", True, lobby.revision)
        lobby.set_ready("guest", True, lobby.revision)
        lobby.configure("host", difficulty="standard")
        self.assertTrue(all(lobby.ready.values()), "unchanged settings must not reset readiness")
        lobby.disconnect()
        with self.assertRaisesRegex(ValueError, "disconnected"):
            lobby.set_ready("guest", True, lobby.revision)


if __name__ == "__main__":
    unittest.main()

