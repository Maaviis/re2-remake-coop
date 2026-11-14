"""Run the host-authoritative pose bridge over the local RE2 Steam plugin."""

import argparse
import json
import math
from pathlib import Path
import sys
import time

from guest_pose import FLOAT32_MAX, PoseFile, validate_player_id
from observer import MAX_OBSERVATION_AGE, StaleObservation, player_proposal, read_sample, valid_motion
from pose_bridge import lock_data_directory
from protocol import v1
from sync_model import Host, Replica, state_digest


MAX_PAYLOAD = 4096
RETRY_INTERVAL = 1
PEER_TIMEOUT = 5


def envelope(kind, **fields):
    return {"version": v1.VERSION, "type": kind, **fields}


def make_proposal(player_id, sample):
    return {"version": v1.VERSION, **player_proposal(player_id, sample)}


def _encode(message):
    payload = v1.encode(message)
    if len(payload) > MAX_PAYLOAD:
        raise v1.ProtocolError("Steam pose frame exceeds the byte limit")
    return payload


def _vectors(value, name, size):
    vector = value[name]
    return (isinstance(vector, list) and len(vector) == size
            and all(type(item) in (int, float) and -FLOAT32_MAX <= item <= FLOAT32_MAX for item in vector))


def _valid_pose(value, now=None):
    if not isinstance(value, dict):
        return False
    required = {"position", "rotation", "observer_sequence", "observer_run_id", "tdb", "observed_at"}
    if not required <= value.keys() or value.keys() - required - {"motion"}:
        return False
    stamp, sequence, run = (value[key] for key in ("observed_at", "observer_sequence", "observer_run_id"))
    if (type(stamp) is not int or not 0 < stamp <= v1.MAX_SAFE_INTEGER
            or (now is not None and not 0 <= now - stamp <= MAX_OBSERVATION_AGE)
            or type(sequence) is not int or not 1 <= sequence <= v1.MAX_SAFE_INTEGER
            or not isinstance(run, str) or not 0 < len(run) <= 128
            or type(value["tdb"]) is not int or value["tdb"] != 70):
        return False
    if value["position"] is None or value["rotation"] is None:
        return value["position"] is value["rotation"] is None and "motion" not in value
    return (_vectors(value, "position", 3) and _vectors(value, "rotation", 4)
            and math.hypot(*value["rotation"]) > 0
            and ("motion" not in value or valid_motion(value["motion"])))


class PoseHost:
    def __init__(self, host_id, guest_id):
        self.host_id = host_id
        self.guest_id = guest_id
        self.state = Host()
        self.ready = False

    def reset_link(self):
        self.ready = False
        previous = self.state.state["players"].get(self.guest_id)
        if previous is not None and previous["position"] is not None:
            cleared = {**previous, "position": None, "rotation": None}
            cleared.pop("motion", None)
            self._emit(self.guest_id, cleared)

    def _emit(self, player, value):
        def validate(event, snapshot):
            _encode(envelope("event", data=event))
            _encode(envelope("snapshot", data=snapshot))

        return envelope("event", data=self.state.emit("player", player, value, validate=validate))

    def _proposal(self, message, player, now):
        if message["type"] != "propose" or message["kind"] != "player" or message["target"] != player:
            return None
        value = message["value"]
        if not _valid_pose(value, now):
            return None
        current = self.state.state["players"].get(player)
        if current is not None:
            if (value["observed_at"] < current["observed_at"]
                    or (value["observer_run_id"] == current["observer_run_id"]
                        and value["observer_sequence"] <= current["observer_sequence"])):
                return None
        return self._emit(player, value)

    def receive(self, message, *, now):
        if message["type"] == "hello":
            self.ready = True
            return envelope("snapshot", data=self.state.snapshot())
        if self.ready and message["type"] == "ping":
            return envelope("pong", nonce=message["nonce"])
        if self.ready:
            return self._proposal(message, self.guest_id, now)
        return None

    def local(self, sample, *, now):
        return self._proposal(make_proposal(self.host_id, sample), self.host_id, now)


class PoseGuest:
    def __init__(self, host_id, guest_id):
        self.players = {host_id, guest_id}
        self.reset()

    def reset(self):
        self.replica = Replica()
        self.ready = False

    def hello(self):
        return envelope("hello")

    def receive(self, message):
        try:
            if message["type"] == "snapshot":
                snapshot = message["data"]
                players = snapshot["state"]["players"]
                if players.keys() - self.players or any(not _valid_pose(value) for value in players.values()):
                    raise ValueError("unexpected player or malformed pose")
                if any(value for key, value in snapshot["state"].items() if key != "players"):
                    raise ValueError("unexpected non-pose state")
                if (self.replica.session_id and self.replica.sequence == snapshot["sequence"]
                        and state_digest(self.replica.state) != snapshot["digest"]):
                    raise ValueError("divergent snapshot")
                self.replica.restore(snapshot)
                self.ready = True
                return True
            if self.ready and message["type"] == "event":
                event = message["data"]
                if (event["kind"] != "player" or event["target"] not in self.players
                        or not _valid_pose(event["value"])):
                    raise ValueError("unexpected event")
                return self.replica.apply(event)
        except ValueError:
            self.ready = False
        return False


def _read(path):
    try:
        sample = read_sample(path, require_fresh=True)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, StaleObservation):
        return None
    return sample if "observed_at" in sample else None

class SteamPipe:
    def __init__(self, pid):
        self.name = rf"\\.\pipe\re2-coop-steam-pose-{pid}"
        self.epoch = None
        self.role = None

    def request(self, data):
        import _winapi as win

        deadline = time.monotonic() + 0.5
        while True:
            try:
                handle = win.CreateFile(self.name, win.GENERIC_READ | win.GENERIC_WRITE, 0,
                                        0, win.OPEN_EXISTING, win.FILE_FLAG_OVERLAPPED, 0)
                break
            except OSError as exc:
                remaining = int((deadline - time.monotonic()) * 1000)
                if exc.winerror != win.ERROR_PIPE_BUSY or remaining <= 0:
                    raise
                win.WaitNamedPipe(self.name, remaining)
        try:
            win.SetNamedPipeHandleState(handle, win.PIPE_READMODE_MESSAGE, None, None)
            for operation, argument in ((win.WriteFile, data), (win.ReadFile, MAX_PAYLOAD + 9)):
                pending, error = operation(handle, argument, overlapped=True)
                if (error == win.ERROR_IO_PENDING
                        and win.WaitForSingleObject(pending.event, 1000) != win.WAIT_OBJECT_0):
                    pending.cancel()
                    pending.GetOverlappedResult(True)
                    raise TimeoutError("RE2 pipe reply timed out")
                count, error = pending.GetOverlappedResult(True)
                if error:
                    raise OSError(error, "RE2 pipe I/O failed")
                if operation == win.WriteFile and count != len(data):
                    raise OSError("RE2 pipe request was not fully written")
            return pending.getbuffer()
        finally:
            win.CloseHandle(handle)

    def receive(self):
        reply = self.request(b"R")
        if reply == b"N":
            self.role = self.epoch = None
            return None
        if len(reply) < 9 or reply[:1] not in (b"H", b"G"):
            raise OSError("invalid RE2 pose pipe response")
        self.role, self.epoch = reply[:1], reply[1:9]
        return reply[9:] or None

    def send(self, message):
        if self.epoch is None or self.request(b"S" + self.epoch + _encode(message)) != b"S":
            raise OSError("RE2 Steam send failed or the peer changed")


def run_bridge(data, transport, role, host_id, guest_id, *, stop=None):
    host = PoseHost(host_id, guest_id) if role == b"H" else None
    guest = None if host else PoseGuest(host_id, guest_id)
    remote_id = guest_id if host else host_id
    local_id = host_id if host else guest_id
    path = data / "re2_coop_observer.json"
    epoch = last_sample = None
    last_contact = next_retry = 0.0
    nonce = 0

    def disconnect(output):
        nonlocal epoch, last_sample, last_contact, next_retry
        if epoch is not None:
            if host:
                host.reset_link()
            else:
                # A local pipe break does not identify a different remote host.
                guest.ready = False
            output.disconnect()
        epoch = last_sample = None
        last_contact = next_retry = 0.0

    with PoseFile(data / "re2_coop_guest_pose.json", remote_id) as output:
        while stop is None or not stop.is_set():
            now = time.monotonic()
            try:
                payload = transport.receive()
            except OSError:
                disconnect(output)
                time.sleep(0.1)
                continue
            if transport.role is not None and transport.role != role:
                raise ValueError("Python bridge role does not match the RE2 Steam lobby role")
            if transport.epoch is None:
                disconnect(output)
                time.sleep(0.05)
                continue
            if transport.epoch != epoch:
                disconnect(output)
                epoch = transport.epoch
                last_contact = now
            if now - last_contact >= PEER_TIMEOUT:
                if host:
                    host.reset_link()
                else:
                    guest.ready = False
                output.disconnect()
                last_sample = None
                last_contact = now

            try:
                message = v1.decode(payload) if payload is not None else None
                if message and host:
                    response = host.receive(message, now=time.time())
                    if response is not None:
                        transport.send(response)
                        last_contact = now
                        if response["type"] in ("event", "snapshot"):
                            output.update(host.state)
                elif message and guest:
                    if (message["type"] == "snapshot" and guest.replica.session_id
                            and guest.replica.session_id != message["data"]["session_id"]):
                        raise ValueError("host bridge restarted; restart the guest bridge to join its new session")
                    was_ready = guest.ready
                    if guest.receive(message):
                        output.update(guest.replica)
                        last_contact = now
                        if message["type"] == "snapshot":
                            # Re-publish after verifying a snapshot following local resync.
                            last_sample = None
                    elif message["type"] == "pong" and guest.ready and message["nonce"] == nonce:
                        last_contact = now
                    elif was_ready and not guest.ready:
                        output.disconnect()
                        last_sample = None
                        next_retry = 0.0

                if guest and now >= next_retry:
                    if guest.ready:
                        nonce = nonce % v1.MAX_SAFE_INTEGER + 1
                        transport.send(envelope("ping", nonce=nonce))
                    else:
                        transport.send(guest.hello())
                    next_retry = now + RETRY_INTERVAL

                sample = _read(path)
                if sample is not None:
                    key = (sample["run_id"], sample["sequence"])
                    if key != last_sample:
                        if host:
                            event = host.local(sample, now=time.time())
                            if event is not None:
                                if host.ready:
                                    transport.send(event)
                                    output.update(host.state)
                            last_sample = key
                        elif guest.ready:
                            transport.send(make_proposal(local_id, sample))
                            last_sample = key
            except v1.ProtocolError:
                # A malformed peer message cannot change the verified state.
                pass
            except OSError:
                disconnect(output)
            time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="REFramework data directory")
    parser.add_argument("--pid", type=int, required=True, help="RE2 process ID")
    parser.add_argument("--role", choices=("host", "guest"), required=True)
    parser.add_argument("--host-id", default="leon")
    parser.add_argument("--guest-id", default="claire")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("the RE2 Steam plugin requires Windows")
    if (not args.data.is_dir() or not 0 < args.pid <= 0xffffffff
            or args.host_id == args.guest_id):
        parser.error("expected an existing data directory, a process ID and distinct player IDs")
    try:
        validate_player_id(args.host_id)
        validate_player_id(args.guest_id)
        with lock_data_directory(args.data):
            run_bridge(args.data, SteamPipe(args.pid), b"H" if args.role == "host" else b"G",
                       args.host_id, args.guest_id)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"Steam pose bridge stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
