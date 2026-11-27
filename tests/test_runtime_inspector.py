import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.runtime_inspector import snapshot


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.data = Path(self.enterContext(TemporaryDirectory()))

    def write(self, name, value):
        (self.data / f"re2_coop_{name}.json").write_text(json.dumps({"schema": 1, **value}))

    def read(self):
        return snapshot(self.data, 100)["sources"]

    def test_independent_sources_and_expired_partner_pose(self):
        self.write("lobby", {"written_at": 100, "role": "H", "connected": True,
                             "lobby": {"data": {"revision": 7, "host_id": "private"}}})
        self.write("guest_pose", {"written_at": 100, "observed_at": 90, "connected": True,
                                  "pose": {"position": [1, 2, 3]}})
        view = self.read()
        self.assertEqual(view["partner_pose"]["observation"], "expired")
        self.assertNotIn("position", view["partner_pose"])
        self.assertEqual(view["lobby"]["revision"], 7)
        self.assertNotIn("private", json.dumps(view))
        self.assertEqual(view["renderer"], {"state": "missing"})

    def test_malformed_future_and_expired_files(self):
        self.write("observer", {"observed_at": 80, "position": [7, 8, 9]})
        self.write("save_guard", {"at": 102})
        (self.data/"re2_coop_lobby.json").write_bytes(b'{"broken":')
        (self.data/"re2_coop_guest_pose.json").write_bytes(b' ' * 65537)
        view = self.read()
        self.assertEqual(view["local_pose"], {"state": "stale", "age_s": 20})
        self.assertEqual(view["campaign"]["state"], "future")
        self.assertEqual(view["lobby"]["state"], "invalid")
        self.assertEqual(view["partner_pose"]["state"], "invalid")

    def test_visible_preview_is_separate_from_campaign_partner(self):
        self.write("dev_inspector", {"at": 99, "status": "sampled",
                   "preview": {"present": True, "mesh_id": "pl0001", "clip": 160, "frame": 2.5},
                   "partner": {"present": False}, "player": {"mesh_id": "C:/private"}})
        self.write("guest_pose", {"written_at": 100, "observed_at": 98, "connected": True,
                                  "pose": {"position": [1, 0, 2], "motion": {"bank": 3, "id": 4}}})
        view = self.read()
        self.assertEqual(view["renderer"]["preview"]["mesh_id"], "pl0001")
        self.assertFalse(view["renderer"]["partner"]["present"])
        self.assertNotIn("private", json.dumps(view))
        self.assertEqual(view["partner_pose"]["observed_age_s"], 2)
        self.assertEqual(view["partner_pose"]["motion"]["id"], 4)
