import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from readonly_save_control import arm, wait_for_result
from tests.test_save_catalog import source


class ReadOnlySaveControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "re2_coop_save_policy.json"
        self.status = self.root / "re2_coop_save_guard.json"
        self.write_status()
        (self.root / "re2_coop_save_catalog.json").write_text(json.dumps(source()))
        self.clock = patch("readonly_save_control.time.time", return_value=100).start()
        self.addCleanup(patch.stopall)

    def write_status(self, **fields):
        self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26,
            "at": 100, "denied_loads": 0, **fields}))

    def test_arm_preserves_native_identity_and_excludes_unrelated_metadata(self):
        request = arm(self.root, "scenario:4", "2026-11-11")
        value = json.loads(self.policy.read_text())
        self.assertEqual(value["id"], request)
        self.assertEqual(value["reference"], {"mode": 1, "slot_id": 4,
            "timestamp": source()["entries"][1]["timestamp"], "scenario": 1})
        self.assertEqual(set(value), {"schema", "id", "at", "reference"})

    def test_disallowed_slot_or_stale_catalog_does_not_replace_a_policy(self):
        arm(self.root, "scenario:4", "2026-11-11")
        before = self.policy.read_bytes()
        with self.assertRaises(ValueError):
            arm(self.root, "scenario:0", "2026-11-11")
        self.assertEqual(self.policy.read_bytes(), before)
        self.clock.return_value = 104
        self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26, "at": 104}))
        with self.assertRaises(ValueError):
            arm(self.root, "scenario:4", "2026-11-11")
        self.assertEqual(self.policy.read_bytes(), before)

    def test_loading_requires_an_explicit_option(self):
        arm(self.root, "scenario:4", "2026-11-11", load=True)
        self.assertIs(json.loads(self.policy.read_text())["load"], True)
        arm(self.root, "scenario:4", "2026-11-11")
        self.assertNotIn("load", json.loads(self.policy.read_text()))

    def test_missing_expired_or_incomplete_native_guard_cannot_arm(self):
        for change in ({"active": False}, {"active": 1}, {"hooks": 25}, {"at": 96}):
            self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26, "at": 100, **change}))
            with self.subTest(change=change), self.assertRaises(ValueError):
                arm(self.root, "scenario:4", "2026-11-11")
        self.assertFalse(self.policy.exists())

    def test_load_after_a_denied_native_request_never_replaces_policy(self):
        arm(self.root, "scenario:4", "2026-11-11")
        before = self.policy.read_bytes()
        for denied in (1, -1, True, None):
            self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26,
                "at": 100, "denied_loads": denied}))
            with self.subTest(denied=denied), self.assertRaisesRegex(ValueError, "native_load_state_requires_reset"):
                arm(self.root, "scenario:4", "2026-11-11", load=True)
            self.assertEqual(self.policy.read_bytes(), before)

    def test_receipt_option_rejects_legacy_probe_before_queuing(self):
        with self.assertRaisesRegex(ValueError, "command receipts"):
            arm(self.root, "scenario:4", "2026-11-11", load=True, require_receipt=True)
        self.assertFalse(self.policy.exists())
        self.write_status(command_id="", command_error="", load_request_id="")
        self.assertEqual(arm(self.root, "scenario:4", "2026-11-11", require_receipt=True),
            json.loads(self.policy.read_text())["id"])

    def test_arm_requires_matching_active_policy_or_reports_rejection(self):
        self.write_status(command_id="ours", command_error="load_in_progress", policy_id="other")
        with self.assertRaisesRegex(ValueError, "load_in_progress"):
            wait_for_result(self.root, "ours", load=False, timeout=3)
        self.write_status(command_id="other", command_error="load_in_progress", policy_id="ours")
        wait_for_result(self.root, "ours", load=False, timeout=3)

    def test_load_waits_for_fresh_matching_scene_even_after_another_command(self):
        self.status.write_text('{"schema":')
        reports = iter((
            {"load_request_id": "other", "load_phase": "scene_loaded"},
            {"load_request_id": "ours", "load_phase": "scene_loaded", "at": 96},
            {"load_request_id": "ours", "load_phase": "loading", "load_error": "load_status_unavailable"},
            {"load_request_id": "ours", "load_phase": "scene_loaded", "command_id": "other",
                "command_error": "load_in_progress"},
        ))

        def advance(_seconds):
            self.write_status(**{"load_error": "", **next(reports)})

        with patch("readonly_save_control.time.sleep", side_effect=advance) as sleep:
            wait_for_result(self.root, "ours", load=True, timeout=3)
        self.assertEqual(sleep.call_count, 4)

    def test_load_reports_terminal_native_failure(self):
        self.write_status(load_request_id="ours", load_phase="failed", load_error="title_menu_close_failed")
        with self.assertRaisesRegex(ValueError, "title_menu_close_failed"):
            wait_for_result(self.root, "ours", load=True, timeout=3)

    def test_load_timeout_reports_last_phase_without_changing_the_mailbox(self):
        arm(self.root, "scenario:4", "2026-11-11", load=True)
        before = self.policy.read_bytes()
        self.write_status(load_request_id="ours", load_phase="loading", load_error="")
        with patch("readonly_save_control.time.monotonic", side_effect=[0, 0, 3]), \
                patch("readonly_save_control.time.sleep"):
            with self.assertRaisesRegex(TimeoutError, "last observed load phase: loading"):
                wait_for_result(self.root, "ours", load=True, timeout=3)
        self.assertEqual(self.policy.read_bytes(), before)
