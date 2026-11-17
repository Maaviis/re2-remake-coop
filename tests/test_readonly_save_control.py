from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from load_preflight import NativeSaveSource
from readonly_save_control import arm, wait_for_result
from save_catalog import SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import state_digest
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

    def prepared_fixture(self, *, role="H"):
        saves = self.root / "saves"
        saves.mkdir()
        save = saves / "data004Slot.bin"
        save.write_bytes(b"synthetic save bytes")
        self.write_status(guard_run_id="native-run", command_id="", command_error="", load_request_id="")
        reference = SaveCatalog(self.root / "re2_coop_save_catalog.json", allow_date="2026-11-11").select("scenario:4")
        body = {"host_id": "leon", "guest_id": "claire", "revision": 7, "connected": True,
                "ready": {"leon": True, "claire": True}, "settings": {}, "save_slot": "scenario:4",
                "save_ref": reference, "load_check": {"phase": "prepared", "revision": 7, "reason": "",
                    "attempt_id": "a" * 32, "save_digest": sha256(save.read_bytes()).hexdigest()}}
        message = {"version": 1, "type": "lobby_state", "session_id": "lobby-session",
                   "sequence": 6, "digest": state_digest(body), "data": body}
        status = {"schema": 1, "written_at": 100, "connected": True, "game_pid": 123, "role": role,
                  "steam_lobby": "owned" if role == "H" else "joined",
                  "steam_membership": {"session_id": "b" * 32, "revision": 9}, "lobby": message}
        native = patch("readonly_save_control.SteamPipe").start()
        native.return_value.lobby_status.return_value = status["steam_lobby"]
        native.return_value.membership_revision.return_value = status["steam_membership"]["revision"]
        native.return_value.save_directory.return_value = saves
        native.return_value.cloud_status.return_value = "cloud-app-disabled"
        native.return_value.request.return_value = b"peer-ready"
        self.native_pipe = native
        self.storage_guard = patch("readonly_save_control._storage_guard_active", return_value=True).start()
        self.write_lobby(status)
        return save, status

    def write_lobby(self, value):
        (self.root / "re2_coop_lobby.json").write_text(json.dumps(value), encoding="utf-8")

    def test_prepared_load_queues_one_identity_for_the_same_attempt(self):
        save, status = self.prepared_fixture(role="G")
        request = arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        command = json.loads(self.policy.read_text())
        self.assertEqual((command["schema"], command["id"], command["load"]), (2, request, True))
        self.native_pipe.assert_called_once_with(123)
        self.assertEqual(command["lobby_load"], {
            "game_pid": 123, "role": "G", "membership": status["steam_membership"],
            "session_id": "lobby-session", "revision": 7, "attempt_id": "a" * 32,
            "save_digest": status["lobby"]["data"]["load_check"]["save_digest"], "guard_run_id": "native-run",
        })
        self.assertNotIn(str(save.parent), self.policy.read_text())
        self.assertEqual(arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent), request)
        status["lobby"]["data"]["load_check"]["attempt_id"] = "c" * 32
        status["lobby"]["digest"] = state_digest(status["lobby"]["data"])
        self.write_lobby(status)
        self.assertNotEqual(arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent),
                            request)

    def test_prepared_load_never_replaces_policy_with_stale_lobby_or_changed_save(self):
        save, status = self.prepared_fixture()
        arm(self.root, "scenario:4", "2026-11-11")
        before = self.policy.read_bytes()
        options = {"load": True, "prepared_lobby": save.parent}
        self.write_lobby({**status, "written_at": 96})
        with self.assertRaisesRegex(ValueError, "fresh connected Steam lobby"):
            arm(self.root, "scenario:4", "2026-11-11", **options)
        self.write_lobby({**status, "steam_membership": None})
        with self.assertRaisesRegex(ValueError, "verified native Steam membership"):
            arm(self.root, "scenario:4", "2026-11-11", **options)
        self.write_lobby(status)
        save.write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "local save bytes differ"):
            arm(self.root, "scenario:4", "2026-11-11", **options)
        self.assertEqual(self.policy.read_bytes(), before)

    def test_prepared_load_rejects_membership_cleared_in_the_native_plugin(self):
        save, _ = self.prepared_fixture()
        self.native_pipe.return_value.membership_revision.return_value = 10
        with self.assertRaisesRegex(ValueError, "native Steam membership changed"):
            arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

    def test_prepared_load_rejects_native_lobby_without_a_peer(self):
        save, _ = self.prepared_fixture()
        self.native_pipe.return_value.request.return_value = b"peer-waiting-for-member"
        with self.assertRaisesRegex(ValueError, "native Steam peer is required"):
            arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

    def test_prepared_load_refuses_an_identical_copy_outside_the_active_steam_directory(self):
        save, _ = self.prepared_fixture()
        alternate = self.root / "other-copy" / "win64_save"
        alternate.mkdir(parents=True)
        (alternate / save.name).write_bytes(save.read_bytes())
        with self.assertRaisesRegex(ValueError, "active Steam save directory"):
            arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=alternate)
        self.assertFalse(self.policy.exists())

    def test_prepared_load_requires_confirmed_disabled_steam_cloud(self):
        save, _ = self.prepared_fixture()
        for state in ("cloud-enabled", "cloud-unavailable"):
            self.native_pipe.return_value.cloud_status.return_value = state
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, state):
                arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
            self.assertFalse(self.policy.exists())
        self.native_pipe.return_value.cloud_status.return_value = "cloud-account-disabled"
        arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.assertTrue(self.policy.exists())

    def test_prepared_load_requires_a_running_windows_storage_guard(self):
        save, _ = self.prepared_fixture()
        arm(self.root, "scenario:4", "2026-11-11")
        original = self.policy.read_bytes()
        self.storage_guard.return_value = False
        with self.assertRaisesRegex(ValueError, "active Windows save guard"):
            arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.storage_guard.assert_called_once_with(save.parent.resolve())
        self.assertEqual(self.policy.read_bytes(), original)

    def test_prepared_load_rejects_replacement_of_the_active_steam_directory(self):
        save, _ = self.prepared_fixture()
        fingerprint = NativeSaveSource.fingerprint

        def swap_save_directory(source, reference):
            digest = fingerprint(source, reference)
            previous = save.parent.rename(self.root / "previous-saves")
            save.parent.mkdir()
            save.write_bytes((previous / save.name).read_bytes())
            return digest

        with (patch.object(NativeSaveSource, "fingerprint", swap_save_directory),
              self.assertRaisesRegex(ValueError, "Steam save directory changed")):
            arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

    def test_native_save_path_requires_the_observed_re2_steam_layout(self):
        pipe = SteamPipe(123)
        steam_app = self.root / "Benutzer" / "883710"
        for payload, expected in (
            (f"user-data-folder {steam_app / 'local'}".encode(), steam_app / "remote" / "win64_save"),
            (f"user-data-folder {self.root / '100' / 'local'}".encode(), None),
            (b"user-data-folder relative/883710/local", None),
            (b"user-data-folder \xff", None),
            (b"user-data-unavailable", None),
        ):
            with self.subTest(payload=payload), patch.object(pipe, "request", return_value=payload) as request:
                self.assertEqual(pipe.save_directory(), expected)
                request.assert_called_once_with(b"user-data-folder", pipe_name=pipe.lobby_name)

    def test_prepared_load_aborts_if_native_membership_changes_during_fingerprinting(self):
        save, status = self.prepared_fixture()
        fingerprint = NativeSaveSource.fingerprint

        def switch_membership(source, reference):
            digest = fingerprint(source, reference)
            status["steam_membership"]["revision"] += 1
            self.write_lobby(status)
            return digest

        with patch.object(NativeSaveSource, "fingerprint", switch_membership):
            with self.assertRaisesRegex(ValueError, "prepared lobby changed"):
                arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

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
