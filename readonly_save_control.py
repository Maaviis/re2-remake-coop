"""Arm the opt-in native test guard, optionally loading one date-filtered save."""

import argparse
import json
import math
from pathlib import Path
import secrets
import sys
import time

from lobby_sync import write_json
from save_catalog import SaveCatalog
from save_protection import read_save_protection


def read_active_guard(data, *, protected=False):
    status = json.loads((data / "re2_coop_save_guard.json").read_text(encoding="utf-8"))
    if (not isinstance(status, dict) or type(status.get("schema")) is not int or status["schema"] != 1
            or status.get("active") is not True
            or type(status.get("hooks")) is not int or status["hooks"] != 26
            or type(status.get("at")) is not int or not 0 <= time.time() - status["at"] <= 3):
        raise ValueError("a fresh active Lua save/load guard with all required hooks is required")
    if protected:
        binding = read_save_protection(data)
        if status.get('protection_active') is not True or status.get('protection') != binding:
            raise ValueError('protected_launch_required: Lua guard is not bound to the protected game')
    return status


def arm(data, key, allow_date, *, load=False, require_receipt=False):
    status = read_active_guard(data, protected=True)
    protection = status['protection']
    if require_receipt and not all(isinstance(status.get(field), str)
            for field in ("command_id", "command_error", "load_request_id")):
        raise ValueError("--wait requires a native save probe with command receipts")
    if load and (type(status.get("denied_loads")) is not int or status["denied_loads"] != 0):
        raise ValueError("native_load_state_requires_reset: a clean isolated test session is required")
    reference = SaveCatalog(data / "re2_coop_save_catalog.json", allow_date=allow_date).select(key)
    value = {"schema": 1, "id": secrets.token_hex(16), "at": int(time.time()), "protection": protection,
             "reference": {field: reference[field] for field in ("mode", "slot_id", "timestamp", "scenario")}}
    if load:
        value["load"] = True
    write_json(data / "re2_coop_save_policy.json", value)
    return value["id"]


def wait_for_result(data, request_id, *, load, timeout):
    deadline = time.monotonic() + timeout
    last_phase = None
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            status = read_active_guard(data, protected=True)
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
    parser.add_argument("--wait", type=float, metavar="SECONDS", help="wait for confirmation of arming or native scene loading")
    parser.add_argument("key", help="eligible native catalog key, for example scenario:4")
    args = parser.parse_args()
    if args.wait is not None and (not math.isfinite(args.wait) or args.wait <= 0):
        parser.error("--wait requires a finite, positive number of seconds")
    try:
        request_id = arm(args.data, args.key, args.allow_save_date, load=args.load, require_receipt=args.wait is not None)
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
