"""Readiness checks for one side of the two-machine RE2 Steam test."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from observer import StaleObservation, read_sample
from steam_pose_bridge import _valid_pose, make_proposal


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
    for path, missing in ((reference, "missing-reference"), (installed, "missing-installed")):
        if not path.is_file():
            return missing
    try:
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


def inspect(repo, game, dll, pid, role, *, motion=False):
    framework = game / "reframework"
    checks = {"plugin": compare(dll, framework / "plugins/re2_coop_steam_lobby_probe.dll")}
    files = ["re2_coop_observer.lua", "re2_coop_guest_pose.lua"]
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

    for key, command in (("lobby", "status"), ("peer", "peer-status")):
        if checks["process"] != "matching":
            checks[key] = "unchecked"
            continue
        try:
            checks[key] = lobby_status(repo, pid, command)
        except (OSError, subprocess.SubprocessError):
            checks[key] = "unavailable"

    checks["observer"] = observer_status(framework / "data/re2_coop_observer.json", started)
    ready = (all(checks[key] == "matching" for key in ("process", "plugin", *files))
             and checks["lobby"] == ("owned" if role == "host" else "joined")
             and checks["peer"] == "peer-round-trip-verified"
             and checks["observer"] == "available")
    return {"role": role, "ready": ready, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="RE2 installation directory")
    parser.add_argument("--dll", type=Path, required=True, help="reference plugin DLL from the test build")
    parser.add_argument("--pid", type=int, required=True, help="running RE2 process ID")
    parser.add_argument("--role", choices=("host", "guest"), required=True)
    parser.add_argument("--motion", action="store_true", help="also verify the optional motion script")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("the RE2 Steam plugin requires Windows")
    if not args.game.is_dir() or not 0 < args.pid <= 2147483647:
        parser.error("expected an existing installation directory and a valid process ID")
    repo = Path(__file__).resolve().parent
    report = inspect(repo, args.game.resolve(), args.dll.resolve(), args.pid, args.role, motion=args.motion)
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
