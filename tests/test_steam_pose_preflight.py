import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lobby_sync import LobbyHost
from steam_pose_preflight import MENU_SCRIPTS, compare, inspect


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
        self.scripts = ("re2_coop_observer.lua", "re2_coop_guest_pose.lua", "re2_coop/campaign_pose_scope.lua")
        for name in (*self.scripts, *MENU_SCRIPTS):
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

    def check(self, statuses=("owned", "peer-round-trip-verified"), *, role="host", motion=False, stage="pose",
              membership=None):
        with (patch("steam_pose_preflight.process_info", return_value=(self.exe, self.started)),
              patch("steam_pose_preflight.lobby_status", side_effect=statuses),
              patch("steam_pose_preflight.SteamPipe.membership_revision", return_value=membership)):
            return inspect(self.repo, self.game, self.dll, 1234, role, motion=motion, stage=stage)

    def write_menu_reports(self, *, role="H", lobby="idle", pid=1234, age=0, reason="inactive",
                           lobby_state=None, **bridge):
        stamp = int(time.time()) - age
        self.file(self.data / "re2_coop_lobby_input.json",
                  json.dumps({"schema": 1, "observed_at": stamp, "reason": reason}).encode())
        self.file(self.data / "re2_coop_lobby.json",
                  json.dumps({"schema": 1, "written_at": stamp, "role": role,
                              "game_pid": pid, "steam_lobby": lobby, "lobby": lobby_state, **bridge}).encode())

    def test_link_stage_verifies_same_session_in_title_menu_for_both_roles(self):
        self.observer_file.unlink()
        host = LobbyHost("session-for-title-test", "leon", "claire")
        host.connect()
        state = host.snapshot()
        reports = []
        for role, marker, lobby, revision in (("host", "H", "owned", 5), ("guest", "G", "joined", 3)):
            self.write_menu_reports(role=marker, lobby=lobby, connected=True, lobby_state=state,
                                    steam_membership={"session_id": role, "revision": revision})
            report = self.check((lobby, "peer-round-trip-verified"), role=role, stage="link", membership=revision)
            self.assertTrue(report["ready"], report)
            self.assertEqual(report["checks"]["bridge_link"], "verified")
            self.assertNotIn("observer", report["checks"])
            self.assertNotIn(state["session_id"], json.dumps(report))
            reports.append(report)
        self.assertEqual(reports[0]["session_fingerprint"], reports[1]["session_fingerprint"])

    def test_link_stage_requires_roundtrip_current_membership_and_valid_bridge_state(self):
        host = LobbyHost("session-for-title-test", "leon", "claire")
        host.connect()
        state = host.snapshot()
        report = {"connected": True, "lobby_state": state,
                  "steam_membership": {"session_id": "local", "revision": 1}}
        for peer, revision, update, expected in (
            ("peer-waiting-for-member", 1, {}, "verified"),
            ("peer-round-trip-verified", None, {}, "membership-unavailable"),
            ("peer-round-trip-verified", 2, {}, "membership-mismatch"),
            ("peer-round-trip-verified", 1, {"connected": False}, "bridge-disconnected"),
            ("peer-round-trip-verified", 1, {"lobby_state": {**state, "digest": "0" * 64}}, "invalid-lobby-state"),
        ):
            with self.subTest(expected=expected):
                self.write_menu_reports(lobby="owned", **(report | update))
                result = self.check(("owned", peer), stage="link", membership=revision)
                self.assertFalse(result["ready"], result)
                self.assertEqual(result["checks"]["bridge_link"], expected)
                self.assertNotIn("session_fingerprint", result)

    def test_menu_stage_checks_both_roles_before_a_pose_or_peer_exists(self):
        self.observer_file.unlink()
        for role, marker, lobby in (("host", "H", "idle"), ("guest", "G", "invite-pending")):
            with self.subTest(role=role):
                self.write_menu_reports(role=marker, lobby=lobby)
                report = self.check((lobby,), role=role, stage="menu")
                self.assertTrue(report["ready"], report)
                self.assertEqual(report["stage"], "menu")
                self.assertNotIn("peer", report["checks"])
                self.assertNotIn("observer", report["checks"])

    def test_menu_stage_reports_stale_or_wrong_bridge_and_unavailable_input(self):
        for changes, check, expected in (
            ({"pid": 999}, "bridge", "different-process"),
            ({"role": "G"}, "bridge", "wrong-role"),
            ({"lobby": "owned"}, "bridge", "lobby-state-mismatch"),
            ({"age": 4}, "bridge", "stale"),
            ({"reason": "unsupported_input_api"}, "menu_input", "input-unavailable"),
        ):
            with self.subTest(changes=changes):
                self.write_menu_reports(**changes)
                report = self.check(("idle",), stage="menu")
                self.assertFalse(report["ready"])
                self.assertEqual(report["checks"][check], expected)

    def test_menu_stage_rejects_an_unchecked_pipe_and_mismatched_menu_script(self):
        self.write_menu_reports()
        (self.game / "reframework" / "autorun" / MENU_SCRIPTS[0]).write_bytes(b"different script")
        report = self.check((TimeoutError(),), stage="menu")
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"]["lobby"], "unavailable")
        self.assertEqual(report["checks"][MENU_SCRIPTS[0]], "hash-mismatch")

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
