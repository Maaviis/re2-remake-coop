"""Arm the opt-in native test guard, optionally loading one date-filtered save."""

import argparse
import json
import math
from pathlib import Path
import secrets
import sys
import time

from load_preflight import NativeSaveSource
from load_witness import _read_json
from lobby_sync import write_json
from protocol import v1
from save_catalog import IDENTITY_FIELDS, SaveCatalog
from steam_pose_bridge import SteamPipe
from sync_model import state_digest


def read_active_guard(data):
    status = json.loads((data / "re2_coop_save_guard.json").read_text(encoding="utf-8"))
    if (not isinstance(status, dict) or type(status.get("schema")) is not int or status["schema"] != 1
            or status.get("active") is not True
            or type(status.get("hooks")) is not int or status["hooks"] != 26
            or type(status.get("at")) is not int or not 0 <= time.time() - status["at"] <= 3):
        raise ValueError("a fresh active native save guard with all required hooks is required")
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


def _prepared_lobby(data):
    scope, lobby = read_connected_lobby(data)
    check = lobby.get("load_check")
    if not check or check["phase"] != "prepared":
        raise ValueError("both peers must prepare the current native save")
    return {**scope, "revision": check["revision"],
            "attempt_id": check["attempt_id"], "save_digest": check["save_digest"]}, lobby["save_ref"]


def arm(data, key, allow_date, *, load=False, require_receipt=False, prepared_lobby=None):
    status = read_active_guard(data)
    if require_receipt and not all(isinstance(status.get(field), str)
            for field in ("command_id", "command_error", "load_request_id")):
        raise ValueError("--wait requires a native save probe with command receipts")
    if load and (type(status.get("denied_loads")) is not int or status["denied_loads"] != 0):
        raise ValueError("native_load_state_requires_reset: a clean isolated test session is required")
    reference = SaveCatalog(data / "re2_coop_save_catalog.json", allow_date=allow_date).select(key)
    value = {"schema": 1,
             "reference": {field: reference[field] for field in IDENTITY_FIELDS}}
    if prepared_lobby is not None:
        run_id = status.get("guard_run_id")
        if not load or not isinstance(run_id, str) or not 0 < len(run_id) <= 128:
            raise ValueError("prepared lobby loading requires --load and an updated native save probe")
        scope, selected = _prepared_lobby(data)
        if any(selected[field] != reference[field] for field in IDENTITY_FIELDS):
            raise ValueError("the local slot differs from the prepared lobby selection")
        source = NativeSaveSource(data, prepared_lobby, allow_date=allow_date)
        if source.fingerprint(selected) != scope["save_digest"]:
            raise ValueError("local save bytes differ from the prepared lobby")
        pipe = SteamPipe(scope["game_pid"])
        expected_state = "owned" if scope["role"] == "H" else "joined"
        if pipe.lobby_status() != expected_state or pipe.membership_revision() != scope["membership"]["revision"]:
            raise ValueError("native Steam membership changed before the load")
        peer = pipe.request(b"peer-status", pipe_name=pipe.lobby_name)
        if peer not in (b"peer-ready", b"peer-ping-pending", b"peer-round-trip-verified"):
            raise ValueError("a native Steam peer is required before the load")
        current_guard = read_active_guard(data)
        if (current_guard.get("guard_run_id") != run_id or type(current_guard.get("denied_loads")) is not int
                or current_guard["denied_loads"] != 0
                or current_guard.get("writes") not in (None, {})):
            raise ValueError("native save guard changed while checking the prepared lobby")
        if _prepared_lobby(data) != (scope, selected):
            raise ValueError("prepared lobby changed while checking the save")
        value["schema"] = 2
        value["lobby_load"] = {**scope, "guard_run_id": run_id}
        value["id"] = state_digest(value["lobby_load"])[:32]
    else:
        value["id"] = secrets.token_hex(16)
    value["at"] = int(time.time())
    if load:
        value["load"] = True
    write_json(data / "re2_coop_save_policy.json", value)
    return value["id"]


def wait_for_result(data, request_id, *, load, timeout):
    deadline = time.monotonic() + timeout
    last_phase = None
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            status = read_active_guard(data)
        except (OSError, ValueError):
            # The probe can be between updates or still writing the JSON report.
            status = {}
        if status.get("command_id") == request_id and status.get("command_error"):
            raise ValueError(f"Read-only command {request_id} rejected: {status['command_error']}")
        if load and status.get("load_request_id") == request_id:
            last_phase = status.get("load_phase")
            if last_phase == "failed":
                error = status.get("load_error") or "unknown native error"
                raise ValueError(f"Native load {request_id} failed: {error}")
            if last_phase == "scene_loaded" and status.get("load_error") == "":
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
            wait_for_result(args.data, request_id, load=args.load, timeout=args.wait)
            if args.load:
                print(f"Native load {request_id} reached scene_loaded.")
            else:
                print(f"Armed read-only policy {request_id}.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
