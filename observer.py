"""Forward read-only REFramework player samples to the local prototype host."""

import argparse
import json
import math
import os
from pathlib import Path
import socket
from threading import Event
import time

from protocol.v1 import MAX_SAFE_INTEGER
from sync_model import Replica, ResyncRequired, state_digest
from wire import CLIENT_REPLY_TIMEOUT, PROTOCOL_VERSIONS, RECONNECT_DELAY, join_replica, receive, send


MAX_OBSERVATION_AGE = 5


class StaleObservation(ValueError):
    """The observer file predates the current observation window."""


def read_sample(path, *, require_fresh=False):
    if require_fresh:
        with Path(path).open(encoding="utf-8") as stream:
            modified_at = os.fstat(stream.fileno()).st_mtime
            sample = json.load(stream)
    else:
        sample = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(sample, dict) or sample.get("schema") != 1 or sample.get("source") != "re2":
        raise ValueError("unsupported observer sample")
    if not isinstance(sample.get("run_id"), str) or not sample["run_id"]:
        raise ValueError("observer run id required")
    sequence = sample.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("invalid observer sequence")
    if "available" in sample or "observed_at" in sample:
        available, observed_at = sample.get("available"), sample.get("observed_at")
        if (type(available) is not bool or type(observed_at) is not int
                or not 0 < observed_at <= MAX_SAFE_INTEGER):
            raise ValueError("invalid observer presence")
    if require_fresh:
        timestamp = sample.get("observed_at", modified_at)
        if not 0 <= time.time() - timestamp <= MAX_OBSERVATION_AGE:
            raise StaleObservation("observer sample is stale or dated in the future")
    if sample.get("available") is False:
        if sample.get("position") is not None or sample.get("rotation") is not None:
            raise ValueError("unavailable observer sample contains a pose")
        return sample
    for name, size in (("position", 3), ("rotation", 4)):
        values = sample.get(name)
        if not isinstance(values, list) or len(values) != size or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in values
        ):
            raise ValueError(f"invalid {name}")
    return sample


def forward_sample(port, player_id, sample, *, protocol_version=0, expected_session=None):
    """Return the matching event or a verified snapshot already containing this sample."""
    proposal = {"type": "propose", "kind": "player", "target": player_id,
                "value": {"position": sample.get("position"),
                          "rotation": sample.get("rotation"),
                          "observer_sequence": sample["sequence"],
                          "observer_run_id": sample["run_id"],
                          "tdb": sample.get("tdb")}}
    if "observed_at" in sample:
        proposal["value"]["observed_at"] = sample["observed_at"]
    sample_digest = state_digest(proposal["value"])
    with socket.create_connection(("127.0.0.1", port), timeout=CLIENT_REPLY_TIMEOUT) as connection:
        with connection.makefile("rwb") as stream:
            replica = join_replica(stream, protocol_version=protocol_version,
                                   replica=Replica(session_id=expected_session))
            if expected_session is not None:
                current = replica.state["players"].get(player_id)
                if state_digest(current) == sample_digest:
                    # The host accepted the sample before the prior connection lost its reply.
                    return replica.snapshot()
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


def run_observer(path, port, player_id, *, protocol_version=0, once=False, stop=None,
                 active_session=None, reconnect_attempts=0):
    stop = stop if stop is not None else Event()
    last_sequence = 0
    run_id = None
    retries = 0
    while not stop.is_set():
        expected_session = active_session() if active_session is not None else None
        if active_session is not None and expected_session is None:
            stop.wait(0.1)
            continue
        try:
            sample = read_sample(path, require_fresh=True)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError, StaleObservation):
            if once:
                raise
            stop.wait(0.1)
            continue
        if run_id is None:
            run_id = sample["run_id"]
        elif sample["run_id"] != run_id:
            raise ValueError("observer run changed: restart this bridge with a fresh host session")
        if sample["sequence"] < last_sequence:
            raise ValueError("observer sequence reset: restart this bridge with a fresh host session")
        if sample["sequence"] > last_sequence:
            try:
                accepted = forward_sample(port, player_id, sample, protocol_version=protocol_version,
                                          expected_session=expected_session)
            except (EOFError, ConnectionError, TimeoutError, ResyncRequired):
                if retries == reconnect_attempts:
                    raise
                retries += 1
                stop.wait(RECONNECT_DELAY)
                continue
            retries = 0
            print(json.dumps({"observer_sequence": sample["sequence"],
                              "host_sequence": accepted["sequence"]}), flush=True)
            last_sequence = sample["sequence"]
        if once:
            return
        stop.wait(0.1)


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
    run_observer(args.file, args.port, args.player_id,
                 protocol_version=args.protocol_version, once=args.once)


if __name__ == "__main__":
    main()
