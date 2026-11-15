"""Arm the opt-in native test guard, optionally loading one date-filtered save."""

import argparse
import json
from pathlib import Path
import secrets
import sys
import time

from lobby_sync import write_json
from save_catalog import SaveCatalog


def arm(data, key, allow_date, *, load=False):
    status = json.loads((data / "re2_coop_save_guard.json").read_text(encoding="utf-8"))
    if (not isinstance(status, dict) or status.get("schema") != 1 or status.get("active") is not True
            or type(status.get("hooks")) is not int or status["hooks"] != 26
            or type(status.get("at")) is not int or not 0 <= time.time() - status["at"] <= 3):
        raise ValueError("a fresh active native save guard with all required hooks is required")
    reference = SaveCatalog(data / "re2_coop_save_catalog.json", allow_date=allow_date).select(key)
    value = {"schema": 1, "id": secrets.token_hex(16), "at": int(time.time()),
             "reference": {field: reference[field] for field in ("mode", "slot_id", "timestamp", "scenario")}}
    if load:
        value["load"] = True
    write_json(data / "re2_coop_save_policy.json", value)
    return value["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--allow-save-date", required=True, help="eligible engine calendar date, YYYY-MM-DD")
    parser.add_argument("--load", action="store_true", help="also request the native read-only load from the title environment")
    parser.add_argument("key", help="eligible native catalog key, for example scenario:4")
    args = parser.parse_args()
    try:
        request_id = arm(args.data, args.key, args.allow_save_date, load=args.load)
        print(f"Queued read-only policy {request_id}; check re2_coop_save_guard.json for acknowledgment.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
