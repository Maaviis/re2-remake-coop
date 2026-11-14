"""Inspect and change the experimental Steam lobby from a terminal."""

import argparse
import json
from pathlib import Path
import secrets
import time

from lobby_sync import validate_choices, write_json


def submit(data, action, value):
    status = json.loads((data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
    if (type(status.get("written_at")) is not int
            or not 0 <= time.time() - status["written_at"] <= 3):
        raise ValueError("lobby bridge status is stale")
    message = status.get("lobby")
    if message is None:
        raise ValueError("waiting for a verified lobby peer")
    if action == "configure":
        if status["role"] != "H":
            raise ValueError("only the host may select a save or settings")
        validate_choices(value["save_slot"], value["settings"])
    elif action != "ready" or type(value) is not bool:
        raise ValueError("invalid lobby command")
    elif not status["connected"]:
        raise ValueError("waiting for a verified lobby peer")
    command = {"id": secrets.token_hex(16), "written_at": int(time.time()),
               "session_id": message["session_id"], "revision": message["data"]["revision"],
               "action": action, "value": value}
    write_json(data / "re2_coop_lobby_command.json", command)
    return command["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    ready = sub.add_parser("ready")
    ready.add_argument("value", choices=("yes", "no"))
    configure = sub.add_parser("configure")
    configure.add_argument("--save-slot", required=True)
    configure.add_argument("--settings", default="{}", help="JSON settings object")
    args = parser.parse_args()
    try:
        if args.action == "status":
            status = json.loads((args.data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
            status["fresh"] = 0 <= time.time() - status.get("written_at", 0) <= 3
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            value = (args.value == "yes" if args.action == "ready" else
                     {"save_slot": args.save_slot, "settings": json.loads(args.settings)})
            command_id = submit(args.data, args.action, value)
            print(f"Queued lobby command {command_id}; check status for the host's result.")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Lobby command failed: {exc}\n")


if __name__ == "__main__":
    main()
