"""Arm the opt-in native test guard, optionally loading one date-filtered save."""

import argparse
import json
import math
from pathlib import Path
import secrets
import sys
import time

from load_preflight import STAGED_LOAD_AGE, NativeSaveSource
from load_witness import _read_json
from lobby_sync import write_json
from protocol import v1
from save_catalog import IDENTITY_FIELDS, SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import state_digest
from prepared_load_pause import held_pause
from save_protection import (active_save_identity as _active_save_identity,
                             read_save_protection, storage_guard_active as _storage_guard_active)


def read_active_guard(data, *, protected=False, allow_runtime=True, runtime_directory=None):
    status = json.loads((data / "re2_coop_save_guard.json").read_text(encoding="utf-8"))
    if (not isinstance(status, dict) or type(status.get("schema")) is not int or status["schema"] != 1
            or status.get("active") is not True
            or type(status.get("hooks")) is not int or status["hooks"] != 26
            or type(status.get("at")) is not int or not 0 <= time.time() - status["at"] <= 3):
        raise ValueError("a fresh active Lua save/load guard with all required hooks is required")
    if protected:
        binding = read_save_protection(data, allow_runtime=allow_runtime, runtime_directory=runtime_directory)
        if status.get('protection_active') is not True or status.get('protection') != binding:
            raise ValueError('protected_launch_required: Lua guard is not bound to the protected game')
    return status


def read_connected_lobby(data):
    status = _read_json(data / "re2_coop_lobby.json")
    if (not isinstance(status, dict) or type(status.get("schema")) is not int or status["schema"] != 1
            or type(status.get("written_at")) is not int or not 0 <= time.time() - status["written_at"] <= 3
            or status.get("connected") is not True
            or (status.get("role"), status.get("steam_lobby")) not in (("H", "owned"), ("G", "joined"))
            or type(status.get("game_pid")) is not int or not 0 < status["game_pid"] <= 0xffffffff):
        raise ValueError("a fresh connected Steam lobby is required")
    membership = status.get("steam_membership")
    if (not isinstance(membership, dict) or set(membership) != {"session_id", "revision"}
            or not isinstance(membership["session_id"], str) or not v1.REQUEST_ID.fullmatch(membership["session_id"])
            or type(membership["revision"]) is not int or not 0 < membership["revision"] <= 0xffffffff):
        raise ValueError("a verified native Steam membership is required")
    message = status.get("lobby")
    v1.encode(message, steam_pose=True)
    if message["type"] != "lobby_state" or state_digest(message["data"]) != message["digest"]:
        raise ValueError("invalid Steam lobby state digest")
    lobby = message["data"]
    if lobby["connected"] is not True:
        raise ValueError("a verified connected lobby state is required")
    return {"game_pid": status["game_pid"], "role": status["role"], "membership": membership,
            "session_id": message["session_id"]}, lobby


def _prepared_lobby(data, *, require_campaign=False):
    scope, lobby = read_connected_lobby(data)
    check = lobby.get("load_check")
    if not check or check["phase"] != "prepared":
        raise ValueError("both peers must prepare the current native save")
    if check.get("admission") != 1:
        raise ValueError("both peers need the coordinated prepared load version")
    if require_campaign and check.get("campaign_start") is not True:
        raise ValueError("runtime protection requires explicit campaign consent from both peers")
    selection = lobby['new_game'] if 'new_game' in lobby else lobby['save_ref']
    return {**scope, "revision": check["revision"],
            "attempt_id": check["attempt_id"], "save_digest": check["save_digest"]}, selection


def arm(data, key, allow_date, *, load=False, require_receipt=False, prepared_lobby=None,
        expected_game_pid=None, expected_role=None):
    status = read_active_guard(data, protected=True, allow_runtime=prepared_lobby is not None,
                               runtime_directory=prepared_lobby)
    protection = status['protection']
    if require_receipt and not all(isinstance(status.get(field), str)
            for field in ("command_id", "command_error", "load_request_id")):
        raise ValueError("--wait requires a native save probe with command receipts")
    if load and (type(status.get("denied_loads")) is not int or status["denied_loads"] != 0):
        raise ValueError("native_load_state_requires_reset: a clean isolated test session is required")
    new_game = isinstance(key, dict)
    value = {"schema": 1, "protection": protection}
    if new_game:
        from lobby_sync import validate_new_game

        validate_new_game(key)
        if (not load or prepared_lobby is None or expected_game_pid is None or status.get('new_game_supported') is not True
                or type(status.get('allowed_load_calls')) is not int or status['allowed_load_calls'] != 0):
            raise ValueError('new game requires a pristine protected coordinated campaign')
        value['new_game'] = dict(key)
    else:
        reference = SaveCatalog(data / "re2_coop_save_catalog.json", allow_date=allow_date).select(key)
        value['reference'] = {field: reference[field] for field in IDENTITY_FIELDS}
    if prepared_lobby is not None:
        prepared_lobby = Path(prepared_lobby)
        run_id = status.get("guard_run_id")
        if not load or not isinstance(run_id, str) or not 0 < len(run_id) <= 128:
            raise ValueError("prepared lobby loading requires --load and an updated native save probe")
        require_campaign = new_game or status.get("runtime_protection") is True
        scope, selected = _prepared_lobby(data, require_campaign=require_campaign)
        if (scope['game_pid'] != protection['game_pid']
                or expected_game_pid is not None and scope['game_pid'] != expected_game_pid
                or expected_role is not None and scope['role'] != expected_role):
            raise ValueError('prepared lobby requires the protected game process')
        if new_game and selected != key:
            raise ValueError('new game selection differs from the prepared lobby')
        if not new_game and any(selected.get(field) != reference[field] for field in IDENTITY_FIELDS):
            raise ValueError("the local slot differs from the prepared lobby selection")
        direct = 'campaign_namespace' in protection
        if direct and not new_game:
            raise ValueError('Dieser Koop-Ordner ist nur für die neue Kampagne freigegeben.')
        source = (NativeSaveSource(data, prepared_lobby, allow_date=None, campaign_binding=protection)
                  if direct else NativeSaveSource(data, prepared_lobby, allow_date=allow_date, managed=new_game))
        pipe = SteamPipe(scope["game_pid"])
        directory_identity = _active_save_identity(pipe, source.directory)
        digest = source.resolve_new_game(selected) if new_game else source.fingerprint(selected)
        if digest != scope["save_digest"]:
            if new_game:
                raise ValueError('new game intent differs from the prepared lobby')
            raise ValueError("local save bytes differ from the prepared lobby")
        expected_state = "owned" if scope["role"] == "H" else "joined"
        if pipe.lobby_status() != expected_state or pipe.membership_revision() != scope["membership"]["revision"]:
            raise ValueError("native Steam membership changed before the load")
        peer = pipe.request(b"peer-status", pipe_name=pipe.lobby_name)
        if peer not in (b"peer-ready", b"peer-ping-pending", b"peer-round-trip-verified"):
            raise ValueError("a native Steam peer is required before the load")
        cloud = pipe.cloud_status()
        if cloud not in ("cloud-app-disabled", "cloud-account-disabled"):
            raise ValueError(f"RE2 Steam Cloud must be confirmed disabled before this test load ({cloud})")
        if _active_save_identity(pipe, prepared_lobby) != directory_identity:
            raise ValueError("the active Steam save directory changed during the comparison")
        current_guard = read_active_guard(data, protected=True, runtime_directory=prepared_lobby)
        if (current_guard.get('protection') != protection or current_guard.get("guard_run_id") != run_id
                or type(current_guard.get("denied_loads")) is not int
                or current_guard["denied_loads"] != 0
                or current_guard.get("writes") not in (None, {})
                or new_game and (current_guard.get('new_game_supported') is not True
                                 or type(current_guard.get('allowed_load_calls')) is not int
                                 or current_guard['allowed_load_calls'] != 0)):
            raise ValueError("native save guard changed while checking the prepared lobby")
        if _prepared_lobby(data, require_campaign=require_campaign) != (scope, selected):
            raise ValueError("prepared lobby changed while checking the save")
        # The PowerShell marker uses its original path spelling. Windows can
        # resolve that same directory differently once the ACL is applied.
        if not _storage_guard_active(prepared_lobby):
            raise ValueError("an active Windows save guard is required for this test load")
        if new_game and source.resolve_new_game(selected) != scope['save_digest']:
            raise ValueError('new game selection changed while checking the managed copy')
        value["schema"] = 4 if new_game else 3
        value["lobby_load"] = {**scope, "guard_run_id": run_id}
        value["id"] = state_digest(value["lobby_load"])[:32]
    else:
        value["id"] = secrets.token_hex(16)
    value["at"] = int(time.time())
    if load:
        value["load"] = True
    policy_path = data / "re2_coop_save_policy.json"
    if prepared_lobby is not None:
        try:
            previous = _read_json(policy_path, max_bytes=4096)
        except (OSError, ValueError):
            previous = None
        if isinstance(previous, dict) and previous.get("id") == value["id"]:
            at = previous.get("at")
            if (type(at) is not int or not 0 <= value["at"] - at <= STAGED_LOAD_AGE
                    or previous != {**value, "at": at}):
                raise ValueError("start a new shared load check before replacing the staged command")
            return value["id"]
    write_json(policy_path, value)
    return value["id"]


def wait_for_result(data, request_id, *, load, timeout, require_pause=False, stop=None):
    deadline = time.monotonic() + timeout
    last_phase = None
    while (remaining := deadline - time.monotonic()) > 0:
        if stop is not None and stop.is_set():
            raise ValueError('local protected campaign attempt stopped')
        try:
            status = read_active_guard(data, protected=True)
        except (OSError, ValueError):
            # The probe can be between updates or still writing the JSON report.
            status = {}
        if status.get("command_id") == request_id and status.get("command_error"):
            raise ValueError(f"Read-only command {request_id} rejected: {status['command_error']}")
        staged = status.get("staged_load")
        if load and isinstance(staged, dict) and staged.get("id") == request_id:
            last_phase = "waiting_for_both_staged_loads"
        if load and status.get("load_request_id") == request_id:
            last_phase = status.get("load_phase")
            if last_phase == "failed":
                error = status.get("load_error") or "unknown native error"
                raise ValueError(f"Native load {request_id} failed: {error}")
            if last_phase == "scene_loaded" and status.get("load_error") == "":
                if not require_pause and status.get('prepared_load') is None:
                    return
                hold = status.get('load_hold')
                if isinstance(hold, dict) and hold.get('phase') in ('lost', 'failed'):
                    raise ValueError(hold.get('reason') or 'native pause failed after the prepared load')
                try:
                    held_pause(status, request_id)
                except ValueError:
                    last_phase = 'waiting_for_native_pause'
                else:
                    return
        if not load and status.get("policy_id") == request_id:
            return
        time.sleep(min(0.2, remaining))
    detail = f" (last observed load phase: {last_phase})" if last_phase else ""
    raise TimeoutError(f"No confirmed result for {request_id} within {timeout:g} seconds{detail}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--allow-save-date", required=True, help="eligible engine calendar date, YYYY-MM-DD")
    parser.add_argument("--load", action="store_true", help="also request the native read-only load from the title environment")
    parser.add_argument("--prepared-lobby", type=Path, metavar="WIN64_SAVE_DIRECTORY",
                        help="bind --load to the current prepared Steam lobby and recheck the local file")
    parser.add_argument("--wait", type=float, metavar="SECONDS", help="wait for confirmation of arming or native scene loading")
    parser.add_argument("key", help="eligible native catalog key, for example scenario:4")
    args = parser.parse_args()
    if args.wait is not None and (not math.isfinite(args.wait) or args.wait <= 0):
        parser.error("--wait requires a finite, positive number of seconds")
    if args.prepared_lobby is not None and not args.load:
        parser.error("--prepared-lobby requires --load")
    if args.prepared_lobby is not None and sys.platform != "win32":
        parser.error("--prepared-lobby requires the Windows Steam plugin")
    try:
        request_id = arm(args.data, args.key, args.allow_save_date, load=args.load, require_receipt=args.wait is not None,
                         prepared_lobby=args.prepared_lobby)
        if args.wait is None:
            print(f"Queued read-only policy {request_id}; check re2_coop_save_guard.json for acknowledgment.")
        else:
            print(f"Queued read-only policy {request_id}; waiting for confirmation.", flush=True)
            wait_for_result(args.data, request_id, load=args.load, timeout=args.wait,
                            require_pause=args.prepared_lobby is not None)
            if args.load:
                if args.prepared_lobby is not None:
                    print(f"Native load {request_id} reached scene_loaded with an owned native pause; gameplay remains paused.")
                else:
                    print(f"Native load {request_id} reached scene_loaded.")
            else:
                print(f"Armed read-only policy {request_id}.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
