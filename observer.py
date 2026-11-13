"""Forward read-only REFramework player samples to the local prototype host."""

import argparse
import json
import math
from pathlib import Path
import socket
import time

from sync_model import state_digest
from wire import CLIENT_REPLY_TIMEOUT, PROTOCOL_VERSIONS, join_replica, receive, send


def read_sample(path):
    sample = json.loads(Path(path).read_text(encoding="utf-8"))
    if sample.get("schema") != 1 or sample.get("source") != "re2":
        raise ValueError("unsupported observer sample")
    if not isinstance(sample.get("run_id"), str) or not sample["run_id"]:
        raise ValueError("observer run id required")
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


def forward_sample(port, player_id, sample, *, protocol_version=0):
    proposal = {"type": "propose", "kind": "player", "target": player_id,
                "value": {"position": sample["position"],
                          "rotation": sample["rotation"],
                          "observer_sequence": sample["sequence"],
                          "observer_run_id": sample["run_id"],
                          "tdb": sample.get("tdb")}}
    sample_digest = state_digest(proposal["value"])
    with socket.create_connection(("127.0.0.1", port), timeout=CLIENT_REPLY_TIMEOUT) as connection:
        with connection.makefile("rwb") as stream:
            replica = join_replica(stream, protocol_version=protocol_version)
            send(stream, proposal, protocol_version=protocol_version)
            deadline = time.monotonic() + CLIENT_REPLY_TIMEOUT
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("host did not acknowledge observer sample")
                connection.settimeout(remaining)
                reply = receive(stream, protocol_version=protocol_version)
                if time.monotonic() >= deadline:
                    raise TimeoutError("host did not acknowledge observer sample")
                if reply.get("type") != "event":
                    raise ValueError(reply.get("message", "host rejected sample"))
                event = reply["data"]
                if (replica.apply(event) and event["kind"] == "player"
                        and event["target"] == player_id
                        and state_digest(event["value"]) == sample_digest):
                    return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True,
                        help="reframework/data/re2_coop_observer.json")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--protocol-version", type=int, choices=PROTOCOL_VERSIONS, default=0,
                        help="match the loopback host's protocol version")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    last_sequence = 0
    run_id = None
    while True:
        if args.file.exists() and time.time() - args.file.stat().st_mtime > 5:
            if args.once:
                raise ValueError("observer sample is stale")
            time.sleep(0.1)
            continue
        try:
            sample = read_sample(args.file)
        except (FileNotFoundError, json.JSONDecodeError):
            if args.once:
                raise
            time.sleep(0.1)
            continue
        if run_id is None:
            run_id = sample["run_id"]
        elif sample["run_id"] != run_id:
            raise ValueError("observer run changed: restart this bridge with a fresh host session")
        if sample["sequence"] < last_sequence:
            raise ValueError("observer sequence reset: restart this bridge with a fresh host session")
        if sample["sequence"] > last_sequence:
            event = forward_sample(args.port, args.player_id, sample,
                                   protocol_version=args.protocol_version)
            print(json.dumps({"observer_sequence": sample["sequence"],
                              "host_sequence": event["sequence"]}), flush=True)
            last_sequence = sample["sequence"]
        if args.once:
            return
        time.sleep(0.1)


if __name__ == "__main__":
    main()
