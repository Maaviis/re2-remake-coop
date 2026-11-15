"""Readiness checks for one side of the two-machine RE2 Steam test."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from observer import StaleObservation, read_sample
from steam_pose_bridge import _valid_pose, make_proposal


MENU_SCRIPTS = ("re2_coop_lobby.lua", "re2_coop/lobby_input.lua", "re2_coop/main_menu.lua")


def process_info(pid):
    command = (
        f"$p = Get-Process -Id {pid} -ErrorAction Stop; "
        "[pscustomobject]@{exe=$p.Path; started=([DateTimeOffset]$p.StartTime)"
        ".ToUnixTimeSeconds()} | ConvertTo-Json -Compress"
    )
    output = subprocess.check_output(
        ["pwsh", "-NoProfile", "-Command", command], timeout=5,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    )
    data = json.loads(output)
    return Path(data["exe"]), data["started"]


def lobby_status(repo, pid, command):
    return subprocess.check_output(
        ["pwsh", "-NoProfile", "-File", str(repo / "network/steam_lobby_probe/lobby.ps1"),
         "-GameProcessId", str(pid), "-Command", command],
        timeout=8, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    ).strip()


def compare(reference, installed):
    try:
        for path, missing in ((reference, "missing-reference"), (installed, "missing-installed")):
            if not path.is_file():
                return missing
        with reference.open("rb") as original, installed.open("rb") as actual:
            matches = hashlib.file_digest(original, "sha256").digest() == (
                hashlib.file_digest(actual, "sha256").digest()
            )
    except OSError:
        return "unreadable"
    return "matching" if matches else "hash-mismatch"


def observer_status(path, started):
    try:
        sample = read_sample(path, require_fresh=True)
    except FileNotFoundError:
        return "missing"
    except StaleObservation:
        return "stale"
    except (OSError, ValueError, OverflowError):
        return "invalid-sample"
    stamp = sample.get("observed_at")
    if stamp is None:
        return "missing-source-time"
    if started is not None and stamp < started:
        return "stale"
    if sample.get("tdb") != 70:
        return "unsupported-tdb"
    if not sample.get("available"):
        return "player-unavailable"
    return "available" if _valid_pose(make_proposal("local", sample)["value"]) else "invalid-pose"


def read_fresh_report(path, stamp_key, started):
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "invalid-report"
    if (not isinstance(report, dict) or type(report.get("schema")) is not int
            or report["schema"] != 1 or type(report.get(stamp_key)) is not int):
        return None, "invalid-report"
    stamp = report[stamp_key]
    if not 0 <= int(time.time()) - stamp <= 3 or started is not None and stamp < started:
        return None, "stale"
    return report, "matching"


def check_menu(data, started, pid, role, native_lobby):
    inputs, input_check = read_fresh_report(data / "re2_coop_lobby_input.json", "observed_at", started)
    if inputs is not None and inputs.get("reason") not in ("inactive", "captured", "release_held_input"):
        input_check = "input-unavailable"
    bridge, bridge_check = read_fresh_report(data / "re2_coop_lobby.json", "written_at", started)
    if bridge is not None:
        if type(bridge.get("game_pid")) is not int or bridge["game_pid"] != pid:
            bridge_check = "different-process"
        elif bridge.get("role") != {"host": "H", "guest": "G"}[role]:
            bridge_check = "wrong-role"
        elif bridge.get("steam_lobby") != native_lobby:
            bridge_check = "lobby-state-mismatch"
    return {"menu_input": input_check, "bridge": bridge_check}


def inspect(repo, game, dll, pid, role, *, motion=False, stage="pose"):
    framework = game / "reframework"
    checks = {"plugin": compare(dll, framework / "plugins/re2_coop_steam_lobby_probe.dll")}
    files = ["re2_coop_observer.lua", "re2_coop_guest_pose.lua"]
    if stage == "menu":
        files.extend(MENU_SCRIPTS)
    if motion:
        files.append("re2_coop_remote_motion.lua")
    for name in files:
        checks[name] = compare(repo / "reframework/autorun" / name, framework / "autorun" / name)

    started = None
    try:
        exe, started = process_info(pid)
        checks["process"] = "matching" if exe.resolve() == (game / "re2.exe").resolve() else (
            "different-installation"
        )
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        checks["process"] = "unavailable"

    commands = [("lobby", "status")]
    if stage == "pose":
        commands.append(("peer", "peer-status"))
    for key, command in commands:
        if checks["process"] != "matching":
            checks[key] = "unchecked"
            continue
        try:
            checks[key] = lobby_status(repo, pid, command)
        except (OSError, subprocess.SubprocessError):
            checks[key] = "unavailable"

    files_ready = all(checks[key] == "matching" for key in ("process", "plugin", *files))
    if stage == "menu":
        checks.update(check_menu(framework / "data", started, pid, role, checks["lobby"]))
        lobby_states = ("idle", "owned") if role == "host" else ("idle", "invite-pending", "joined")
        ready = (files_ready and checks["lobby"] in lobby_states
                 and checks["menu_input"] == checks["bridge"] == "matching")
        return {"role": role, "stage": "menu", "ready": ready, "checks": checks}

    checks["observer"] = observer_status(framework / "data/re2_coop_observer.json", started)
    ready = (files_ready and checks["lobby"] == ("owned" if role == "host" else "joined")
             and checks["peer"] == "peer-round-trip-verified"
             and checks["observer"] == "available")
    return {"role": role, "ready": ready, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="RE2 installation directory")
    parser.add_argument("--dll", type=Path, required=True, help="reference plugin DLL from the test build")
    parser.add_argument("--pid", type=int, required=True, help="running RE2 process ID")
    parser.add_argument("--role", choices=("host", "guest"), required=True)
    parser.add_argument("--stage", choices=("menu", "pose"), default="pose",
                        help="check menu prerequisites before inviting, or verify an active pose test")
    parser.add_argument("--motion", action="store_true", help="also verify the optional motion script")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("the RE2 Steam plugin requires Windows")
    if not args.game.is_dir() or not 0 < args.pid <= 2147483647:
        parser.error("expected an existing installation directory and a valid process ID")
    repo = Path(__file__).resolve().parent
    report = inspect(repo, args.game.resolve(), args.dll.resolve(), args.pid, args.role,
                     motion=args.motion, stage=args.stage)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
