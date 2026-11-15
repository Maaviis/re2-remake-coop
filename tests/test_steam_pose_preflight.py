import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from steam_pose_preflight import compare, inspect


class SteamPosePreflightTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.repo = self.root / "repo"
        self.game = self.root / "game"
        self.data = self.game / "reframework" / "data"
        self.data.mkdir(parents=True)
        self.dll = self.root / "build" / "re2_coop_steam_lobby_probe.dll"
        self.file(self.dll, b"test plugin bytes")
        self.installed = self.game / "reframework" / "plugins" / self.dll.name
        self.file(self.installed, self.dll.read_bytes())
        self.scripts = ("re2_coop_observer.lua", "re2_coop_guest_pose.lua")
        for name in self.scripts:
            self.file(self.repo / "reframework" / "autorun" / name, name.encode())
            self.file(self.game / "reframework" / "autorun" / name, name.encode())
        self.exe = self.game / "re2.exe"
        self.file(self.exe, b"test process path")
        self.started = int(time.time()) - 30
        self.observer_file = self.data / "re2_coop_observer.json"
        self.observation = {
            "schema": 1, "source": "re2", "run_id": "one", "sequence": 2,
            "available": True, "tdb": 70, "observed_at": int(time.time()),
            "position": [1, 2, 3], "rotation": [0, 0, 0, 1],
        }
        self.write_sample()

    def file(self, path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def write_sample(self):
        self.observer_file.write_text(json.dumps(self.observation), encoding="utf-8")

    def check(self, statuses=("owned", "peer-round-trip-verified"), *, role="host", motion=False):
        with (patch("steam_pose_preflight.process_info", return_value=(self.exe, self.started)),
              patch("steam_pose_preflight.lobby_status", side_effect=statuses)):
            return inspect(self.repo, self.game, self.dll, 1234, role, motion=motion)

    def test_host_and_guest_with_matching_files_and_live_pose_are_ready(self):
        for role, state in (("host", "owned"), ("guest", "joined")):
            with self.subTest(role=role):
                report = self.check((state, "peer-round-trip-verified"), role=role)
                self.assertTrue(report["ready"])
                self.assertEqual(report["checks"]["observer"], "available")

    def test_solo_lobby_and_menu_sample_have_separate_statuses(self):
        self.observation.update(available=False, position=None, rotation=None)
        self.write_sample()
        report = self.check(("owned", "peer-waiting-for-member"))
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["lobby"], "owned")
        self.assertEqual(report["checks"]["peer"], "peer-waiting-for-member")
        self.assertEqual(report["checks"]["observer"], "player-unavailable")

    def test_wrong_process_skips_pipe_and_detects_installation_mismatches(self):
        with (patch("steam_pose_preflight.process_info", return_value=(self.root / "other" / "re2.exe", self.started)),
              patch("steam_pose_preflight.lobby_status") as pipe):
            self.installed.write_bytes(b"different build")
            report = inspect(self.repo, self.game, self.dll, 1234, "guest", motion=True)
        pipe.assert_not_called()
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["process"], "different-installation")
        self.assertEqual(report["checks"]["plugin"], "hash-mismatch")
        self.assertEqual(report["checks"]["re2_coop_remote_motion.lua"], "missing-reference")

    def test_freshness_checks_reject_old_files_zero_rotation_and_wrong_tdb(self):
        for values, expected in (
            ({"observed_at": self.started - 1}, "stale"),
            ({"observed_at": int(time.time()), "rotation": [0, 0, 0, 0]}, "invalid-pose"),
            ({"rotation": [0, 0, 0, 1], "tdb": 71}, "unsupported-tdb"),
        ):
            with self.subTest(values=values):
                self.observation.update(values)
                self.write_sample()
                report = self.check()
                self.assertFalse(report["ready"])
                self.assertEqual(report["checks"]["observer"], expected)

    def test_failed_pipe_produces_a_report(self):
        report = self.check((TimeoutError(), TimeoutError()))
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["lobby"], "unavailable")
        self.assertEqual(report["checks"]["peer"], "unavailable")

    def test_unreadable_file_metadata_is_reported_instead_of_aborting(self):
        with patch.object(Path, "is_file", side_effect=PermissionError("metadata access denied")):
            self.assertEqual(compare(self.dll, self.installed), "unreadable")


if __name__ == "__main__":
    unittest.main()
