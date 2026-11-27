"""Record host-observed cutscene inputs and arm one occurrence for a protected solo replay."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

from lobby_sync import write_json
from protocol import v1


MAX_MS = 600_000
MAX_CHANGES = 180
MAX_BYTES = 192 * 1024


class SceneRecorder:
    """Only validated host samples and published guest views reach the recording."""
    def __init__(self, directory):
        self.directory = directory
        self.key = self.path = self.previous = None
        self.written = self.files = 0
        self.last_ms = self.last_write = 0

    def append(self, row):
        with self.path.open("a", encoding="ascii") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")

    def close(self, reason):
        if self.path:
            try:
                self.append({"ms": self.last_ms, "end": reason})
            except OSError:
                pass
        self.path = self.previous = None

    def observe(self, scope, host, peer, now):
        if host is None:
            if self.path:
                self.close("host_sample_lost")
            self.key = None
            return
        key = (scope["attempt_id"], host["event"], host["occurrence"])
        try:
            if self.key != key:
                self.close("scene_changed")
                self.key = key
                if self.files >= 128 or not v1.REQUEST_ID.fullmatch(scope["session_id"]):
                    return
                folder = self.directory / "re2_coop_logs" / scope["session_id"]
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"scene-{host['event']}-{host['occurrence']}-{uuid4().hex[:12]}.jsonl"
                with path.open("x", encoding="ascii") as stream:
                    print(json.dumps({"schema": 1, "kind": "host_cutscene", "build": scope["package_commit"],
                                      "event": host["event"], "occurrence": host["occurrence"],
                                      "attempt": scope["attempt_id"], "join": scope["request_id"]}), file=stream)
                self.path, self.start, self.last_ms, self.last_write = path, now, 0, 0
                self.files += 1
                self.written = 0
            if not self.path:
                return
            ms = int((now - self.start) * 1000)
            if ms > MAX_MS:
                self.close("limit")
                return
            self.last_ms = ms
            if (host, peer) != self.previous:
                if self.written >= MAX_CHANGES:
                    self.close("limit")
                    return
                self.append({"ms": ms, "host": host, "peer": peer})
                self.written += 1
                self.previous = host, peer
                self.last_write = ms
            elif ms - self.last_write >= 2000:
                self.append({"ms": ms})
                self.last_write = ms
        except OSError as exc:
            self.path = None
            print(f"Cutscene recording unavailable ({type(exc).__name__})", file=sys.stderr)


def load_trace(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Aufnahme zu groß")
    # A crash may leave an incomplete final append. Use complete lines only.
    lines = raw.split(b"\n")[:-1]
    if not lines:
        raise ValueError("Keine vollständige Aufnahme")
    header = json.loads(lines[0])
    if (not isinstance(header, dict) or header.get("schema") != 1 or header.get("kind") != "host_cutscene"
            or not re.fullmatch("[0-9a-f]{40}", str(header.get("build")))):
        raise ValueError("Unbekanntes Aufnahmeformat")
    groups = []
    last = 0
    end = None
    changes = 0
    for line in lines[1:]:
        row = json.loads(line)
        if not isinstance(row, dict) or end is not None:
            raise ValueError("Ungültige Ereignisfolge")
        ms = row.get("ms")
        if type(ms) is not int or not last <= ms <= MAX_MS:
            raise ValueError("Ungültiger Zeitstempel")
        last = ms
        if set(row) == {"ms", "end"} and row["end"] in ("scene_changed", "scope_closed", "host_sample_lost", "limit"):
            end = row["end"]
        elif set(row) == {"ms", "host", "peer"}:
            host, peer = row["host"], row["peer"]
            v1.check_cutscene_state(host)
            if peer is not None:
                v1.check_cutscene_state(peer)
            if (host["event"], host["occurrence"]) != (header.get("event"), header.get("occurrence")):
                raise ValueError("Szenenkennung wechselt in der Aufnahme")
            changes += 1
            if changes > MAX_CHANGES:
                raise ValueError("Zu viele Zustandswechsel")
            if not groups or host != groups[-1]["host"]:
                groups.append({"host": host, "start": ms, "steps": []})
            groups[-1]["steps"].append({"ms": ms - groups[-1]["start"], "peer": peer or False})
        elif set(row) != {"ms"}:
            raise ValueError("Ungültiger Aufnahmeeintrag")
    if not groups:
        raise ValueError("Keine beobachtete Szene")
    for i, group in enumerate(groups):
        stop = groups[i + 1]["start"] if i+1 < len(groups) else last
        group["duration"] = stop - group.pop("start")
    return {"event": header["event"], "occurrence": header["occurrence"], "build": header["build"],
            "end": end or "partial", "groups": groups}


def arm(trace, game):
    data = game / "reframework/data"
    status = json.loads((data / "re2_coop_solo_status.json").read_bytes())
    if (not isinstance(status, dict) or status.get("schema") != 1 or status.get("active") is not True
            or type(status.get("at")) is not int or not 0 <= int(time.time()) - status["at"] <= 2
            or type(status.get("game_pid")) is not int or status["game_pid"] <= 0
            or not v1.REQUEST_ID.fullmatch(str(status.get("attempt_id")))
            or not isinstance(status.get("request_id"), str) or not 0 < len(status["request_id"]) <= 96):
        raise ValueError("Zuerst den geschützten Solotest in der leeren Host-Lobby starten.")
    current = json.loads((game / "re2-coop/build-info.json").read_bytes())["source_commit"]
    plan = dict(trace, schema=1, replay_id=uuid4().hex, **{k: status[k] for k in ("game_pid","attempt_id","request_id")})
    if len(json.dumps(plan, ensure_ascii=False).encode()) > 65536:
        raise ValueError("Replay-Plan zu groß")
    write_json(data / "re2_coop_scene_replay.json", plan)
    print(f"Replay für {trace['event']} #{trace['occurrence']} aktiviert. Aufnahme {trace['build']}, Testbuild {current}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--game", type=Path, help="Replay in der laufenden isolierten Solositzung aktivieren")
    args = parser.parse_args()
    try:
        trace = load_trace(args.recording)
        if args.game:
            arm(trace, args.game)
        else:
            print(json.dumps(trace, indent=2))
    except (OSError, ValueError, KeyError, RecursionError) as exc:
        parser.exit(1, f"Replay: {exc}\n")


if __name__ == "__main__":
    main()
