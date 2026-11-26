from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from load_preflight import NativeSaveSource, read_staged_load
from readonly_save_control import arm, main, read_active_guard, wait_for_result
from save_catalog import SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import state_digest
from tests.test_save_catalog import source
from tests.test_save_protection import write_protection


class ReadOnlySaveControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / "re2_coop_save_policy.json"
        self.status = self.root / "re2_coop_save_guard.json"
        write_protection(self.root)
        self.write_status()
        (self.root / "re2_coop_save_catalog.json").write_text(json.dumps(source()))
        self.clock = patch("readonly_save_control.time.time", return_value=100).start()
        self.addCleanup(patch.stopall)

    def write_status(self, **fields):
        self.status.write_text(json.dumps({"schema": 1, "active": True, "hooks": 26,
            "at": 100, "denied_loads": 0, "protection_active": True,
            "protection": {"game_pid": 42, "run_id": "a" * 32}, **fields}))

    def test_independent_lua_and_native_publications_must_converge_before_use(self):
        binding = {'game_pid': 42, 'run_id': 'a'*32, 'campaign_namespace': 'b'*32}
        self.write_status(protection=binding)
        matched = json.loads(self.status.read_bytes())
        other = {**matched, 'protection': {**binding, 'campaign_namespace': 'c'*32}}
        with patch('readonly_save_control.read_save_protection', return_value=binding) as native:
            with patch('readonly_save_control._read_json', side_effect=[other, matched]):
                self.assertEqual(read_active_guard(self.status.parent, protected=True), matched)
            self.assertEqual(native.call_count, 2)
            with patch('readonly_save_control._read_json', return_value=other):
                with self.assertRaisesRegex(ValueError, 'campaign_namespace'):
                    read_active_guard(self.status.parent, protected=True)

    def test_arm_preserves_native_identity_and_excludes_unrelated_metadata(self):
        request = arm(self.root, "scenario:4", "2026-11-11")
        value = json.loads(self.policy.read_text())
        self.assertEqual(value["id"], request)
        self.assertEqual(value["reference"], {"mode": 1, "slot_id": 4,
            "timestamp": source()["entries"][1]["timestamp"], "scenario": 1})
        self.assertEqual(set(value), {"schema", "id", "at", "reference", "protection"})
        self.assertEqual(value['protection'], {'game_pid': 42, 'run_id': 'a' * 32})

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
            self.write_status(denied_loads=denied)
            with self.subTest(denied=denied), self.assertRaisesRegex(ValueError, "native_load_state_requires_reset"):
                arm(self.root, "scenario:4", "2026-11-11", load=True)
            self.assertEqual(self.policy.read_bytes(), before)

    def test_26_hooks_alone_or_replayed_protection_never_replace_policy(self):
        arm(self.root, 'scenario:4', '2026-11-11', load=True)
        before = self.policy.read_bytes()
        for changes in ({'protection_active': False}, {'protection': {'game_pid': 43, 'run_id': 'a' * 32}},
                        {'protection': {'game_pid': 42, 'run_id': 'b' * 32}}, {'protection': None}):
            self.write_status(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                arm(self.root, 'scenario:4', '2026-11-11', load=True)
            self.assertEqual(self.policy.read_bytes(), before)
        self.write_status()
        (self.root / 're2_coop_protected_launch.json').unlink()
        with self.assertRaises(OSError):
            arm(self.root, 'scenario:4', '2026-11-11', load=True)
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
                    "attempt_id": "a" * 32, "save_digest": sha256(save.read_bytes()).hexdigest(), "admission": 1}}
        message = {"version": 1, "type": "lobby_state", "session_id": "lobby-session",
                   "sequence": 6, "digest": state_digest(body), "data": body}
        status = {"schema": 1, "written_at": 100, "connected": True, "game_pid": 123, "role": role,
                  "steam_lobby": "owned" if role == "H" else "joined",
                  "steam_membership": {"session_id": "b" * 32, "revision": 9}, "lobby": message}
        from tests.test_save_protection import protection_documents
        native_proof, launch_proof = protection_documents()
        write_protection(self.root, {**native_proof, 'game_pid': 123}, {**launch_proof, 'game_pid': 123})
        self.write_status(guard_run_id="native-run", command_id="", command_error="", load_request_id="",
                          protection={'game_pid': 123, 'run_id': 'a' * 32})
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

    def test_new_game_stages_a_managed_system_only_profile_and_requires_current_proofs(self):
        from campaign_save_copy import open_save_session

        _, status = self.prepared_fixture(role='G')
        saves = self.root / 'userdata/1/883710/remote/win64_save'
        saves.mkdir(parents=True)
        (saves / 'data00-1.bin').write_bytes(b'synthetic system settings')
        self.native_pipe.return_value.save_directory.return_value = saves
        selection = {'scenario': 'CLAIRE_A', 'difficulty': 'HARD'}
        message = status['lobby']
        lobby = message['data']
        del lobby['save_ref']
        lobby.update(save_slot=None, new_game=selection)
        lobby['load_check'].update(campaign_start=True, save_digest=state_digest({'new_game': selection}))
        message['digest'] = state_digest(lobby)
        self.write_lobby(status)
        # A new campaign may have no scenario slots and no native save catalog yet.
        (self.root / 're2_coop_save_catalog.json').unlink()
        proof = {'game_pid': 123, 'run_id': 'a' * 32}
        fields = dict(guard_run_id='native-run', protection=proof, command_id='', command_error='',
                      load_request_id='', allowed_load_calls=0, new_game_supported=True)
        self.write_status(**fields)
        opts = dict(load=True, require_receipt=True, prepared_lobby=saves, expected_game_pid=123, expected_role='G')
        with self.assertRaises(ValueError):
            arm(self.root, selection, None, **opts)
        self.assertFalse(self.policy.exists())
        with open_save_session(saves, lambda: None) as session:
            session.install()
            try:
                request = arm(self.root, selection, None, **opts)
                command = json.loads(self.policy.read_bytes())
                self.assertEqual(set(command), {'schema', 'new_game', 'protection', 'at', 'id', 'load', 'lobby_load'})
                self.assertEqual((command['schema'], command['new_game']), (4, selection))
                self.write_status(**fields, staged_load={'id': request, 'requested_at': 100})
                args = self.root, message, 'G', 123, status['steam_membership']
                self.assertEqual(read_staged_load(*args), request)
                self.write_status(**{**fields, 'allowed_load_calls': 1}, staged_load={'id': request, 'requested_at': 100})
                self.assertIsNone(read_staged_load(*args))
                self.write_status(**{**fields, 'new_game_supported': False})
                with self.assertRaises(ValueError):
                    arm(self.root, selection, None, **opts)
                self.assertEqual(json.loads(self.policy.read_bytes()), command)
            finally:
                session.restore()
        self.assertEqual(sorted(p.name for p in saves.iterdir()), ['data00-1.bin'])

    def test_prepared_load_rejects_protection_for_another_process(self):
        save, status = self.prepared_fixture()
        status['game_pid'] = 124
        self.write_lobby(status)
        with self.assertRaisesRegex(ValueError, 'protected game process'):
            arm(self.root, 'scenario:4', '2026-11-11', load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

    def test_prepared_load_checks_acl_proof_using_the_wrappers_directory_spelling(self):
        save, _ = self.prepared_fixture()
        (save.parent / 'alias').mkdir()
        supplied = save.parent / 'alias' / '..'
        self.assertEqual(supplied.resolve(), save.parent.resolve())
        self.storage_guard.side_effect = lambda directory: directory == supplied
        arm(self.root, 'scenario:4', '2026-11-11', load=True, prepared_lobby=supplied)
        self.assertEqual(json.loads(self.policy.read_text())['schema'], 3)

    def test_prepared_load_rejects_a_new_launch_during_fingerprinting(self):
        save, _ = self.prepared_fixture()
        fingerprint = NativeSaveSource.fingerprint

        def relaunch(source, reference):
            result = fingerprint(source, reference)
            from tests.test_save_protection import protection_documents
            native, launch = protection_documents()
            write_protection(self.root, {**native, 'game_pid': 123, 'run_id': 'e' * 32},
                             {**launch, 'game_pid': 123, 'run_id': 'e' * 32})
            self.write_status(guard_run_id='native-run', protection={'game_pid': 123, 'run_id': 'e' * 32})
            return result

        with (patch.object(NativeSaveSource, 'fingerprint', relaunch),
              self.assertRaisesRegex(ValueError, 'native save guard changed')):
            arm(self.root, 'scenario:4', '2026-11-11', load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

    def test_prepared_load_queues_one_identity_for_the_same_attempt(self):
        save, status = self.prepared_fixture(role="G")
        request = arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        command = json.loads(self.policy.read_text())
        self.assertEqual((command["schema"], command["id"], command["load"]), (3, request, True))
        self.native_pipe.assert_called_once_with(123)
        self.assertEqual(command["lobby_load"], {
            "game_pid": 123, "role": "G", "membership": status["steam_membership"],
            "session_id": "lobby-session", "revision": 7, "attempt_id": "a" * 32,
            "save_digest": status["lobby"]["data"]["load_check"]["save_digest"], "guard_run_id": "native-run",
        })
        self.assertNotIn(str(save.parent), self.policy.read_text())
        self.clock.return_value = 101
        self.assertEqual(arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent), request)
        self.assertEqual(json.loads(self.policy.read_text()), command)
        status["lobby"]["data"]["load_check"]["attempt_id"] = "c" * 32
        status["lobby"]["digest"] = state_digest(status["lobby"]["data"])
        self.write_lobby(status)
        self.assertNotEqual(arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent),
                            request)

    def test_stage_receipt_matches_the_current_command_launch_and_membership(self):
        save, status = self.prepared_fixture(role='G')
        request = arm(self.root, 'scenario:4', '2026-11-11', load=True, prepared_lobby=save.parent)
        message = status['lobby']
        args = (self.root, message, 'G', 123, status['steam_membership'])
        proof = {'game_pid': 123, 'run_id': 'a' * 32}
        self.assertIsNone(read_staged_load(*args))
        self.write_status(guard_run_id='native-run', protection=proof,
                          staged_load={'id': request, 'requested_at': 100})
        self.assertEqual(read_staged_load(*args), request)
        self.assertIsNone(read_staged_load(*args[:-1], {**args[-1], 'revision': 10}))
        with patch('load_preflight.time.time', return_value=121):
            self.assertIsNone(read_staged_load(*args))
        (self.root / 're2_coop_protected_launch.json').unlink()
        self.assertIsNone(read_staged_load(*args))

    def test_old_host_cannot_queue_a_coordinated_local_load(self):
        save, status = self.prepared_fixture(role='G')
        status['lobby']['data']['load_check'].pop('admission')
        status['lobby']['digest'] = state_digest(status['lobby']['data'])
        self.write_lobby(status)
        with self.assertRaisesRegex(ValueError, 'coordinated prepared load version'):
            arm(self.root, 'scenario:4', '2026-11-11', load=True, prepared_lobby=save.parent)
        self.assertFalse(self.policy.exists())

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

    def test_prepared_load_waits_for_the_matching_owned_pause(self):
        request = 'd' * 32
        status = {'guard_run_id': 'native', 'prepared_load': {'scope': {'guard_run_id': 'native'}},
                  'load_request_id': request, 'load_phase': 'scene_loaded', 'load_error': ''}
        hold = {'schema': 1, 'scope': 'prepared_load_native_pause', 'observed_at': 100,
                'guard_run_id': 'native', 'load_request_id': request, 'pause_id': request,
                'phase': 'held', 'native_phase': 'held', 'available': True, 'reason': ''}
        self.write_status(**status, load_hold={**hold, 'pause_id': 'e' * 32})

        def confirm_pause(_):
            self.write_status(**status, load_hold=hold)

        with patch('readonly_save_control.time.sleep', side_effect=confirm_pause) as sleep:
            wait_for_result(self.root, request, load=True, timeout=1)
        self.assertEqual(sleep.call_count, 1)

    def test_prepared_load_without_pause_times_out_without_replacing_policy(self):
        self.policy.write_bytes(b'pending native request fixture')
        self.write_status(guard_run_id='native', prepared_load={'scope': {'guard_run_id': 'native'}},
                          load_request_id='d' * 32, load_phase='scene_loaded', load_error='')
        with (patch('readonly_save_control.time.monotonic', side_effect=[0, 0, 2]),
              patch('readonly_save_control.time.sleep')):
            with self.assertRaisesRegex(TimeoutError, 'waiting_for_native_pause'):
                wait_for_result(self.root, 'd' * 32, load=True, timeout=1)
        self.assertEqual(self.policy.read_bytes(), b'pending native request fixture')

    def test_prepared_cli_does_not_report_success_when_native_load_binding_is_missing(self):
        save, _ = self.prepared_fixture()
        request_id = arm(self.root, "scenario:4", "2026-11-11", load=True, prepared_lobby=save.parent)
        self.write_status(guard_run_id="native-run", command_id="", command_error="",
                          load_request_id=request_id, load_phase="scene_loaded", load_error="",
                          protection={'game_pid': 123, 'run_id': 'a' * 32})
        argv = ["readonly_save_control.py", "--data", str(self.root), "--allow-save-date", "2026-11-11",
                "--load", "--prepared-lobby", str(save.parent), "--wait", "1", "scenario:4"]
        output, errors = io.StringIO(), io.StringIO()
        with (patch.object(sys, "argv", argv), patch.object(sys, "platform", "win32"),
              patch("readonly_save_control.time.monotonic", side_effect=[0, 0, 2]),
              patch("readonly_save_control.time.sleep"), redirect_stdout(output), redirect_stderr(errors)):
            result = main()
        self.assertEqual(result, 1, "a prepared load was reported complete without its native pause")
        self.assertIn("waiting_for_native_pause", errors.getvalue())
        self.assertNotIn("reached scene_loaded", output.getvalue())

    def test_prepared_load_reports_an_externally_ended_pause(self):
        self.write_status(guard_run_id='native', prepared_load={'scope': {'guard_run_id': 'native'}},
                          load_request_id='d' * 32, load_phase='scene_loaded', load_error='',
                          load_hold={'phase': 'lost', 'reason': 'pause_ended_externally'})
        with self.assertRaisesRegex(ValueError, 'pause_ended_externally'):
            wait_for_result(self.root, 'd' * 32, load=True, timeout=1)

    def test_load_timeout_reports_last_phase_without_changing_the_mailbox(self):
        arm(self.root, "scenario:4", "2026-11-11", load=True)
        before = self.policy.read_bytes()
        self.write_status(load_request_id="ours", load_phase="loading", load_error="")
        with patch("readonly_save_control.time.monotonic", side_effect=[0, 0, 3]), \
                patch("readonly_save_control.time.sleep"):
            with self.assertRaisesRegex(TimeoutError, "last observed load phase: loading"):
                wait_for_result(self.root, "ours", load=True, timeout=3)
        self.assertEqual(self.policy.read_bytes(), before)
