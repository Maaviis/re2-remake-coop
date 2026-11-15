import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from readonly_save_control import arm
from tests.test_save_catalog import source


class ReadOnlySaveControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "re2_coop_save_policy.json"
        self.status = self.root / "re2_coop_save_guard.json"
        self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26, "at": 100, "denied_loads": 0}))
        (self.root / "re2_coop_save_catalog.json").write_text(json.dumps(source()))
        self.clock = patch("readonly_save_control.time.time", return_value=100).start()
        self.addCleanup(patch.stopall)

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
