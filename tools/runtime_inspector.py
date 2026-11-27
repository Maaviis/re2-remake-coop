"""Read one local RE2 instance's diagnostic snapshots as JSON (or JSON Lines)."""
import argparse
import json
import math
from pathlib import Path
import re
import time


def obj(value):
    return value if isinstance(value, dict) else {}


def number(value):
    return type(value) in (float, int) and -1e38 <= value <= 1e38 and math.isfinite(value)


def selected(source, *keys):
    return {k: source[k] for k in keys if type(source.get(k)) is bool or number(source.get(k))}


def phase(value):
    phases = {"idle", "armed", "loading", "scene_loaded", "failed", "held", "released",
              "closing_menu", "waiting", "blocked", "preparing", "reheld", "requested"}
    return value if isinstance(value, str) and value in phases else "unknown"


def lobby(data, now):
    details = obj(obj(data.get("lobby")).get("data"))
    out = selected(data, "connected", "bridge_stopped", "game_pid")
    out.update(selected(details, "revision"))
    if data.get("role") in ("H", "G"):
        out["role"] = data["role"]
    if re.fullmatch(r"[a-f0-9]{40}", str(data.get("source_commit"))):
        out["commit"] = data["source_commit"]
    return out


def campaign(data, now):
    hold = obj(data.get("load_hold"))
    return {**selected(data, "active", "protection_active", "in_title", "has_player"),
            "load_phase": phase(data.get("load_phase")), "native_hold": phase(hold.get("native_phase"))}


def pose(data, now):
    result = selected(data, "sequence", "tdb", "connected", "available")
    stamp = data.get("observed_at")
    if type(stamp) is not int or not 0 <= now - stamp <= 5:
        return {**result, "observation": "expired" if type(stamp) is int else "missing"}
    value = obj(data.get("pose")) if "connected" in data else data
    if data.get("connected") is False or data.get("available") is False or not value:
        return {**result, "observation": "unavailable"}
    position = value.get("position")
    if not isinstance(position, list) or len(position) != 3 or not all(map(number, position)):
        return {**result, "observation": "invalid"}
    return {**result, "observation": "sampled", "observed_age_s": now-stamp, "position": position,
            "motion": selected(obj(value.get("motion")), "bank", "id", "frame", "end_frame")}


def renderer(data, now):
    if data.get("status") != "sampled":
        return {"status": "scene_unavailable" if data.get("status") == "scene_unavailable" else "read_error"}
    out = {"status": "sampled"}
    for key in ("player", "partner", "preview"):
        row = obj(data.get(key))
        out[key] = selected(row, "present", "read_error", "draw_self", "mesh_ready", "joints_constructed",
                            "bank", "clip", "frame")
        if re.fullmatch(r"pl[0-9]{4}", str(row.get("mesh_id"))):
            out[key]["mesh_id"] = row["mesh_id"]
    return out


# All timestamps are emitted on this PC, including the receive-side partner pose lease.
SOURCES = {
    "lobby": ("lobby", "written_at", 5, lobby),
    "campaign": ("save_guard", "at", 3, campaign),
    "local_pose": ("observer", "observed_at", 5, pose),
    "partner_pose": ("guest_pose", "written_at", 5, pose),
    "renderer": ("dev_inspector", "at", 3, renderer),
}


def snapshot(directory, now):
    sources = {}
    for key, (name, clock, lease, project) in SOURCES.items():
        try:
            with (directory / f"re2_coop_{name}.json").open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized receipt")
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
                raise ValueError("unsupported receipt")
            stamp = data.get(clock)
            if type(stamp) is not int or stamp <= 0:
                raise ValueError("missing timestamp")
            age = now - stamp
            if age < 0:
                sources[key] = {"state": "future"}
            elif age > lease:
                sources[key] = {"state": "stale", "age_s": age}
            else:
                sources[key] = {"state": "fresh", "age_s": age, **project(data, now)}
        except FileNotFoundError:
            sources[key] = {"state": "missing"}
        except OSError:
            sources[key] = {"state": "unreadable"}
        except (ValueError, RecursionError):
            sources[key] = {"state": "invalid"}
    return {"schema": 1, "sampled_at": now, "sources": sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="Local directory containing re2.exe")
    parser.add_argument("--watch", action="store_true", help="Emit a snapshot every second until Ctrl+C")
    args = parser.parse_args()
    data = args.game / "reframework/data"
    if not data.is_dir():
        parser.error("REFramework data directory missing")
    try:
        while True:
            print(json.dumps(snapshot(data, int(time.time())), allow_nan=False), flush=True)
            if not args.watch:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
