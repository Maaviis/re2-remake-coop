from copy import deepcopy
import unittest

from lobby_sync import LobbyGuest, LobbyHost
from protocol.v1 import ProtocolError, decode, encode
from steam_pose_bridge import PoseGuest, PoseHost


class LobbySyncTests(unittest.TestCase):
    def test_new_handshake_invalidates_ready_even_if_host_did_not_time_out(self):
        host = PoseHost("leon", "claire", lobby_config={"save_slot": "slot-1"})
        guest = PoseGuest("leon", "claire")
        request = guest.hello()
        guest.receive(host.receive(request, now=100))
        guest.receive(host.lobby.snapshot())
        delayed = guest.lobby.ready_message(True)
        host.receive(delayed, now=100)
        revision = host.lobby.lobby.revision
        host.receive(request, now=100)
        self.assertEqual(host.lobby.lobby.revision, revision)
        self.assertTrue(host.lobby.lobby.ready["claire"])
        guest.reset_link()
        guest.receive(host.receive(guest.hello(), now=100))
        self.assertGreater(host.lobby.lobby.revision, revision)
        host.receive(delayed, now=100)
        self.assertFalse(any(host.lobby.lobby.ready.values()))

    def test_host_choices_readiness_and_rejoin_share_one_revision(self):
        host = LobbyHost("session", "leon", "claire", save_slot="slot-1")
        guest = LobbyGuest("leon", "claire")
        host.connect()
        initial = host.snapshot()
        self.assertTrue(guest.receive(initial, "session"))
        ready = decode(encode(guest.ready_message(True), steam_pose=True), steam_pose=True)
        host.set_ready("claire", ready["value"], ready["revision"])
        host.set_ready("leon", True, host.lobby.revision)
        host.configure("slot-2", {"difficulty": "standard"}, host.lobby.revision)
        changed = host.snapshot()
        self.assertFalse(any(changed["data"]["ready"].values()))
        self.assertTrue(guest.receive(changed, "session"))
        with self.assertRaises(ValueError):
            host.set_ready("claire", ready["value"], ready["revision"])
        host.disconnect()
        host.connect()
        with self.assertRaises(ValueError):
            host.set_ready("claire", True, changed["data"]["revision"])
        self.assertTrue(guest.receive(host.snapshot(), "session"))

    def test_replica_rejects_corruption_rollback_and_other_session(self):
        host = LobbyHost("session", "leon", "claire")
        host.connect()
        guest = LobbyGuest("leon", "claire")
        first = host.snapshot()
        host.configure("slot-1", {}, host.lobby.revision)
        current = host.snapshot()
        self.assertTrue(guest.receive(current, "session"))
        self.assertFalse(guest.receive(first, "session"))
        bad = deepcopy(current)
        bad["data"]["save_slot"] = "slot-forged"
        self.assertFalse(guest.receive(bad, "session"))
        self.assertFalse(guest.receive(current, "other-session"))
        self.assertEqual(guest.message, current)

    def test_lobby_frames_are_steam_only_and_bounded(self):
        host = LobbyHost("session", "leon", "claire")
        host.connect()
        frame = host.snapshot()
        self.assertEqual(decode(encode(frame, steam_pose=True), steam_pose=True), frame)
        with self.assertRaises(ProtocolError):
            encode(frame)
        frame["data"]["ready"]["intruder"] = True
        with self.assertRaises(ProtocolError):
            encode(frame, steam_pose=True)
        before = host.snapshot()
        with self.assertRaises(ValueError):
            host.configure("slot-2", {"oversized": "x" * 1024}, host.lobby.revision)
        self.assertEqual(host.snapshot(), before)
