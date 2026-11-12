"""Forward read-only REFramework player samples to the local prototype host."""

import argparse
import json
import math
from pathlib import Path
import socket
import time

from wire import receive, send


def read_sample(path):
    sample = json.loads(Path(path).read_text(encoding="utf-8"))
    if sample.get("schema") != 1 or sample.get("source") != "re2":
        raise ValueError("unsupported observer sample")
    sequence = sample.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("invalid observer sequence")
    for name, size in (("position", 3), ("rotation", 4)):
        values = sample.get(name)
        if not isinstance(values, list) or len(values) != size or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in values
        ):
            raise ValueError(f"invalid {name}")
    return sample


def forward_sample(port, player_id, sample):
    proposal = {"type": "propose", "kind": "player", "target": player_id,
                "value": {"position": sample["position"],
                          "rotation": sample["rotation"],
                          "observer_sequence": sample["sequence"],
                          "tdb": sample.get("tdb")}}
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(5)
        with connection.makefile("rwb") as stream:
            greeting = receive(stream)
            if greeting.get("type") != "snapshot":
                raise ValueError("expected host snapshot")
            send(stream, proposal)
            reply = receive(stream)
            if reply.get("type") != "event":
                raise ValueError(reply.get("message", "host rejected sample"))
            return reply["data"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True,
                        help="reframework/data/re2_coop_observer.json")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    last_sequence = 0
    while True:
        try:
            sample = read_sample(args.file)
        except (FileNotFoundError, json.JSONDecodeError):
            if args.once:
                raise
            time.sleep(0.1)
            continue
        if sample["sequence"] < last_sequence:
            raise ValueError("observer sequence reset: restart this bridge with a fresh host session")
        if sample["sequence"] > last_sequence:
            event = forward_sample(args.port, args.player_id, sample)
            print(json.dumps({"observer_sequence": sample["sequence"],
                              "host_sequence": event["sequence"]}), flush=True)
            last_sequence = sample["sequence"]
        if args.once:
            return
        time.sleep(0.1)


if __name__ == "__main__":
    main()

