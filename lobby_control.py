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
    if action == "join-invite":
        offer = status.get("steam_invite")
        if (status.get("role") != "G" or status.get("steam_lobby") != "invite-pending"
                or message is not None or status.get("connected") or not isinstance(offer, dict)
                or not isinstance(offer.get("session_id"), str)
                or type(offer.get("revision")) is not int or not 0 < offer["revision"] <= 0xffffffff
                or value is not True):
            raise ValueError("a current Steam invite on the guest bridge is required")
        session_id, revision = offer["session_id"], offer["revision"]
    elif action == "leave":
        membership = status.get("steam_membership")
        active_state = (status.get("role"), status.get("steam_lobby"))
        if (active_state not in (("H", "owned"), ("G", "joined")) or not isinstance(membership, dict)
                or not isinstance(membership.get("session_id"), str) or not membership["session_id"]
                or type(membership.get("revision")) is not int or not 0 < membership["revision"] <= 0xffffffff
                or value is not True):
            raise ValueError("a current Steam lobby membership is required")
        session_id, revision = membership["session_id"], membership["revision"]
    else:
        session_id, revision = lobby_target(status, action, value)
    command = {"id": secrets.token_hex(16), "written_at": int(time.time()),
               "session_id": session_id, "revision": revision, "action": action, "value": value}
    write_json(data / "re2_coop_lobby_command.json", command)
    return command["id"]


def lobby_target(status, action, value):
    message = status.get("lobby")
    if message is None:
        raise ValueError("waiting for a verified lobby peer")
    if action in ("configure", "create", "invite", "check-load", "start-campaign", "cancel-load-check"):
        if status["role"] != "H":
            raise ValueError("only the host may perform this lobby action")
        if action == "create" and status.get("steam_lobby") != "idle":
            raise ValueError("Steam lobby creation requires an idle Steam plugin")
        if action == "configure":
            validate_choices(value["save_slot"], value["settings"])
        elif value is not True:
            raise ValueError("invalid host command")
    elif action == "ready-campaign":
        if (status.get("role") != "G" or status.get("campaign_start_supported") is not True
                or status.get("connected") is not True or value is not True):
            raise ValueError("campaign readiness requires the protected connected guest")
    elif action != "ready" or type(value) is not bool:
        raise ValueError("invalid lobby command")
    elif not status["connected"]:
        raise ValueError("waiting for a verified lobby peer")
    return message["session_id"], message["data"]["revision"]


def select_save(data, key):
    status = json.loads((data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
    if key not in {entry["key"] for entry in (status.get("catalog") or {}).get("entries", [])}:
        raise ValueError("select an available RE2 save from the current catalog")
    return submit(data, "configure", {"save_slot": key, "settings": status["lobby"]["data"]["settings"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("create")
    sub.add_parser("invite")
    sub.add_parser("join-invite")
    sub.add_parser("leave")
    sub.add_parser("check-load")
    sub.add_parser("start-campaign")
    sub.add_parser("ready-campaign")
    sub.add_parser("cancel-load-check")
    sub.add_parser("show")
    sub.add_parser("hide")
    pose_probe = sub.add_parser("pose-probe", help="control the local remote-pose mannequin test")
    pose_probe.add_argument("probe_action", choices=("start", "stop"))
    sub.add_parser("saves")
    select = sub.add_parser("select")
    select.add_argument("key", help="native catalog key, for example scenario:4")
    ready = sub.add_parser("ready")
    ready.add_argument("value", choices=("yes", "no"))
    configure = sub.add_parser("configure")
    configure.add_argument("--save-slot", required=True)
    configure.add_argument("--settings", default="{}", help="JSON settings object")
    args = parser.parse_args()
    try:
        if args.action in ("show", "hide"):
            write_json(args.data / "re2_coop_lobby_view.json", {"visible": args.action == "show", "id": secrets.token_hex(8)})
        elif args.action == "pose-probe":
            write_json(args.data / "re2_coop_guest_pose_command.json", {
                "schema": 1, "action": args.probe_action, "nonce": secrets.token_hex(16),
                "issued_at": int(time.time()),
            })
            print(f"Queued local remote-pose test {args.probe_action}; check REFramework log for the result.")
        elif args.action in ("status", "saves"):
            status = json.loads((args.data / "re2_coop_lobby.json").read_text(encoding="utf-8"))
            status["fresh"] = 0 <= time.time() - status.get("written_at", 0) <= 3
            if args.action == "saves":
                if not status["fresh"] or not status.get("catalog"):
                    raise ValueError("fresh native host save catalog required")
                print(json.dumps(status["catalog"], ensure_ascii=False, indent=2))
            else:
                print(json.dumps(status, ensure_ascii=False, indent=2))
        elif args.action == "select":
            command_id = select_save(args.data, args.key)
            print(f"Queued save selection {command_id}; check status for the host's result.")
        else:
            value = True
            if args.action == "ready":
                value = args.value == "yes"
            elif args.action == "configure":
                value = {"save_slot": args.save_slot, "settings": json.loads(args.settings)}
            command_id = submit(args.data, args.action, value)
            print(f"Queued lobby command {command_id}; check status for the host's result.")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Lobby command failed: {exc}\n")


if __name__ == "__main__":
    main()
