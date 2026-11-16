"""Run the host-authoritative pose bridge over the local RE2 Steam plugin."""

import argparse
from contextlib import nullcontext
import json
import math
from pathlib import Path
import secrets
import sys
import time

from guest_pose import FLOAT32_MAX, PoseFile, validate_player_id
from lobby_sync import LobbyFiles, LobbyGuest, LobbyHost
from load_preflight import CHECK_INTERVAL, NativeSaveSource
from observer import MAX_OBSERVATION_AGE, StaleObservation, player_proposal, read_sample, valid_motion
from pose_bridge import lock_data_directory
from protocol import v1
from save_catalog import SaveCatalog
from sync_model import Host, Replica, state_digest


MAX_PAYLOAD = 4096
RETRY_INTERVAL = 1
PEER_TIMEOUT = 5
MAX_RETIRED_RUNS = 256
LOBBY_INTERVAL = 1


def envelope(kind, **fields):
    return {"version": v1.VERSION, "type": kind, **fields}


def make_proposal(player_id, sample):
    return {"version": v1.VERSION, **player_proposal(player_id, sample)}


def _encode(message):
    payload = v1.encode(message, steam_pose=True)
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
    def __init__(self, host_id, guest_id, *, lobby_config=None):
        self.host_id = host_id
        self.guest_id = guest_id
        self.membership_revision = None
        self._start_session(lobby_config)

    def _start_session(self, lobby_config):
        self.state = Host()
        self.lobby = (LobbyHost(self.state.session_id, self.host_id, self.guest_id, **lobby_config)
                      if lobby_config is not None else None)
        self.lobby_request_id = None
        self.ready = False
        self.pose_deadlines = {}
        self.retired_runs = {self.host_id: set(), self.guest_id: set()}

    def bind_membership(self, revision):
        if revision is None or self.membership_revision == revision:
            return False
        previous, self.membership_revision = self.membership_revision, revision
        if previous is None:
            return False
        config = None
        if self.lobby is not None:
            config = {"save_slot": self.lobby.lobby.save_slot, "settings": self.lobby.lobby.settings,
                      "catalog": self.lobby.catalog, "load_source": self.lobby.load_source}
        self._start_session(config)
        return True

    def reset_link(self):
        self.ready = False
        self._clear_pose(self.guest_id)
        if self.lobby:
            self.lobby.disconnect()

    def _clear_pose(self, player):
        if player not in self.pose_deadlines:
            return None
        previous = self.state.state["players"][player]
        cleared = {**previous, "position": None, "rotation": None}
        cleared.pop("motion", None)
        event = self._emit(player, cleared)
        del self.pose_deadlines[player]
        return event

    def expire_poses(self):
        now = time.monotonic()
        return [self._clear_pose(player)
                for player, deadline in tuple(self.pose_deadlines.items())
                if now >= deadline]

    def _emit(self, player, value):
        def validate(event, snapshot):
            _encode(envelope("event", data=event))
            _encode(envelope("snapshot", data=snapshot, request_id="0" * 32))

        return envelope("event", data=self.state.emit("player", player, value, validate=validate))

    def _proposal(self, message, player, now):
        if message["type"] != "propose" or message["kind"] != "player" or message["target"] != player:
            return None
        value = message["value"]
        # The guest's wall clock is independent of the host's. The guest bridge
        # already checks freshness against its own observer before sending.
        if not _valid_pose(value, now if player == self.host_id else None):
            return None
        current = self.state.state["players"].get(player)
        run = value["observer_run_id"]
        retired = self.retired_runs[player]
        if run in retired:
            return None
        replaced_run = None
        if current is not None:
            current_run = current["observer_run_id"]
            if player == self.host_id and value["observed_at"] < current["observed_at"]:
                return None
            if run == current_run:
                if value["observer_sequence"] <= current["observer_sequence"]:
                    return None
            else:
                if len(retired) >= MAX_RETIRED_RUNS:
                    return None
                replaced_run = current_run
        event = self._emit(player, value)
        if replaced_run is not None:
            retired.add(replaced_run)
        if value["position"] is None:
            self.pose_deadlines.pop(player, None)
        else:
            age = now - value["observed_at"] if player == self.host_id else 0
            self.pose_deadlines[player] = time.monotonic() + MAX_OBSERVATION_AGE - age
        return event

    def receive(self, message, *, now):
        if message["type"] == "hello":
            self.expire_poses()
            self.ready = True
            if self.lobby:
                if self.lobby_request_id != message["request_id"]:
                    self.lobby.disconnect()
                self.lobby.connect()
                self.lobby_request_id = message["request_id"]
            return envelope("snapshot", data=self.state.snapshot(), request_id=message["request_id"])
        if self.ready and message["type"] == "ping":
            return envelope("pong", nonce=message["nonce"])
        if self.ready and message.get("session_id") == self.state.session_id:
            if message["type"] == "lobby_load_ack" and self.lobby:
                self.lobby.acknowledge_load(message)
                return None
            if message["type"] == "lobby_ready" and self.lobby:
                try:
                    self.lobby.set_ready(self.guest_id, message["value"], message["revision"],
                                         save_identity=message.get("save_identity"))
                except ValueError:
                    pass
                return None
            return self._proposal(message, self.guest_id, now)
        return None

    def local(self, sample, *, now):
        return self._proposal(make_proposal(self.host_id, sample), self.host_id, now)


class PoseGuest:
    def __init__(self, host_id, guest_id, *, catalog=None):
        self.players = {host_id, guest_id}
        self.replica = Replica()
        self.lobby = LobbyGuest(host_id, guest_id, catalog=catalog)
        self.reset_link()

    def reset_link(self):
        self.ready = False
        self.request_id = None
        self.lobby.message = None

    def hello(self):
        if self.request_id is None:
            self.request_id = secrets.token_hex(16)
        return envelope("hello", request_id=self.request_id)

    def receive(self, message):
        try:
            if self.ready and message["type"] == "lobby_state":
                return self.lobby.receive(message, self.replica.session_id)
            if message["type"] == "snapshot":
                if self.ready or self.request_id is None or self.request_id != message.get("request_id"):
                    return False
                snapshot = message["data"]
                players = snapshot["state"]["players"]
                if players.keys() - self.players or any(not _valid_pose(value) for value in players.values()):
                    raise ValueError("unexpected player or malformed pose")
                if any(value for key, value in snapshot["state"].items() if key != "players"):
                    raise ValueError("unexpected non-pose state")
                replica = self.replica
                if replica.session_id != snapshot["session_id"]:
                    replica = Replica()
                elif (replica.sequence == snapshot["sequence"]
                      and state_digest(replica.state) != snapshot["digest"]):
                    raise ValueError("divergent snapshot")
                replica.restore(snapshot)
                self.replica = replica
                self.request_id = None
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
        self.lobby_name = rf"\\.\pipe\re2-coop-steam-lobby-{pid}"
        self.epoch = None
        self.role = None

    def request(self, data, *, pipe_name=None):
        import _winapi as win

        deadline = time.monotonic() + 0.5
        while True:
            try:
                handle = win.CreateFile(pipe_name or self.name, win.GENERIC_READ | win.GENERIC_WRITE, 0,
                                        0, win.OPEN_EXISTING, win.FILE_FLAG_OVERLAPPED, 0)
                break
            except OSError as exc:
                remaining = int((deadline - time.monotonic()) * 1000)
                if exc.winerror != win.ERROR_PIPE_BUSY or remaining <= 0:
                    raise
                win.WaitNamedPipe(pipe_name or self.name, remaining)
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

    def invite_dialog(self):
        reply = self.request(b"invite-dialog", pipe_name=self.lobby_name)
        if reply != b"accepted invite-dialog":
            raise ValueError("Steam invitation unavailable; check the owned Steam lobby")

    def lobby_status(self):
        try:
            status = self.request(b"status", pipe_name=self.lobby_name).decode("ascii")
        except (OSError, UnicodeError):
            return "unavailable"
        if status in {"idle", "owned", "creating", "invite-pending", "joining", "verifying",
                      "joined", "leaving", "canceling"}:
            return status
        return "unavailable"

    def create_lobby(self):
        if self.lobby_status() != "idle":
            raise ValueError("Steam lobby creation requires an idle Steam plugin")
        if self.request(b"create", pipe_name=self.lobby_name) != b"accepted create":
            raise ValueError("Steam lobby creation rejected by the native plugin")

    def invite_revision(self):
        return self._lobby_revision(b"invite-revision")

    def membership_revision(self):
        return self._lobby_revision(b"membership-revision")

    def _lobby_revision(self, command):
        try:
            reply = self.request(command, pipe_name=self.lobby_name)
        except OSError:
            return None
        if reply.isdigit() and len(reply) <= 10:
            revision = int(reply)
            if 0 < revision <= 0xffffffff:
                return revision
        return None

    def join_invite(self, revision):
        command = f"join-invite {revision}".encode("ascii")
        if self.request(command, pipe_name=self.lobby_name) != b"accepted join-invite":
            raise ValueError("Steam invitation changed or the lobby is busy")

    def leave_lobby(self, revision):
        command = f"leave {revision}".encode("ascii")
        if self.request(command, pipe_name=self.lobby_name) != b"accepted leave":
            raise ValueError("Steam lobby membership changed")


def run_bridge(data, transport, role, host_id, guest_id, *, stop=None, lobby_config=None,
               lobby_enabled=False, save_catalog=None, load_source=None):
    if save_catalog is not None and not lobby_enabled:
        raise ValueError("native save catalog requires the lobby")
    if load_source is not None and (not lobby_enabled or role == b"H" and save_catalog is None):
        raise ValueError("shared load preflight requires the lobby and the host native catalog")
    if load_source is not None and role == b"G" and save_catalog is None:
        save_catalog = load_source.catalog
    config = dict(lobby_config or {})
    if save_catalog is not None and role == b"H":
        config["catalog"] = save_catalog
    if load_source is not None and role == b"H":
        config["load_source"] = load_source
    host = (PoseHost(host_id, guest_id, lobby_config=config if lobby_enabled else None)
            if role == b"H" else None)
    guest = None if host else PoseGuest(host_id, guest_id, catalog=save_catalog)
    remote_id = guest_id if host else host_id
    local_id = host_id if host else guest_id
    path = data / "re2_coop_observer.json"
    epoch = last_sample = None
    last_contact = next_retry = 0.0
    nonce = 0
    lobby_files = LobbyFiles(data) if lobby_enabled else None
    next_lobby = 0.0
    next_load_ack = 0.0
    guest_ready_sent = None
    steam_status = getattr(transport, "lobby_status", None) if lobby_files else None
    invite_revision = getattr(transport, "invite_revision", None) if guest and steam_status else None
    membership_revision = getattr(transport, "membership_revision", None) if host or steam_status else None
    steam_session = secrets.token_hex(16) if steam_status else None
    steam_invite = steam_membership = None
    steam_lobby, next_steam_status = None, 0.0

    def update_lobby(now):
        nonlocal next_lobby, next_load_ack, guest_ready_sent, steam_lobby, next_steam_status
        nonlocal steam_invite, steam_membership
        if steam_status is not None and now >= next_steam_status:
            previous_steam_lobby, steam_lobby = steam_lobby, steam_status()
            next_steam_status = now + 1.0
            if guest and previous_steam_lobby in ("joining", "verifying", "canceling"):
                if steam_lobby in ("idle", "invite-pending"):
                    lobby_files.error = "Steam did not confirm the lobby join"
            revision = invite_revision() if invite_revision and steam_lobby == "invite-pending" else None
            steam_invite = {"session_id": steam_session, "revision": revision} if revision else None
            expected_membership = "owned" if host else "joined"
            revision = (membership_revision()
                        if membership_revision and steam_lobby == expected_membership else None)
            steam_membership = {"session_id": steam_session, "revision": revision} if revision else None
            if host and host.bind_membership(revision):
                disconnect(output)
        if lobby_files is None:
            return
        link_ready = host.ready if host else guest.ready
        last_guest_lobby = guest.lobby.message if guest and link_ready else None
        lobby_message = host.lobby.snapshot() if host else None
        local_save_matches, guest_revision = None, None
        if last_guest_lobby is not None:
            lobby_message = guest.lobby.current_message()
            guest_revision = (last_guest_lobby["session_id"], last_guest_lobby["data"]["revision"])
        if guest and lobby_message is not None and "save_ref" in lobby_message["data"]:
            local_save_matches = guest.lobby.matching_save_identity() is not None
        if guest_ready_sent != guest_revision:
            guest_ready_sent = None
        elif guest_ready_sent is not None and (lobby_message is None or local_save_matches is False):
            transport.send(guest.lobby.ready_message(False))
            guest_ready_sent = None
        command_lobby = lobby_message or last_guest_lobby
        invite_scope = steam_invite if command_lobby is None and not link_ready else None
        scope = ({"session_id": command_lobby["session_id"], "revision": command_lobby["data"]["revision"]}
                 if command_lobby is not None else invite_scope)
        if scope is not None or steam_membership is not None:
            command = lobby_files.command(scope, steam_membership=steam_membership)
        else:
            command = None
        if command is not None:
            if command["action"] == "leave":
                try:
                    if command["value"] is not True:
                        raise ValueError("an explicit Steam lobby departure is required")
                    transport.leave_lobby(command["revision"])
                except (OSError, ValueError) as exc:
                    lobby_files.error = str(exc)
                else:
                    steam_lobby, steam_membership = "leaving", None
                    disconnect(output)
                    lobby_files.publish(host.lobby.snapshot() if host else None, False, role,
                                        steam_lobby=steam_lobby)
                    return
            elif command_lobby is not None:
                try:
                    if lobby_message is None:
                        raise ValueError("guest lobby state expired")
                    if command["action"] == "ready" and type(command["value"]) is bool:
                        if host:
                            host.lobby.set_ready(local_id, command["value"], command["revision"])
                        elif link_ready:
                            transport.send(guest.lobby.ready_message(command["value"]))
                            guest_ready_sent = guest_revision if command["value"] else None
                    elif command["action"] == "configure" and host:
                        value = command["value"]
                        if not isinstance(value, dict) or set(value) != {"save_slot", "settings"}:
                            raise ValueError("invalid lobby choices")
                        # Empty Lua tables are serialized as null by REFramework.
                        settings = {} if value["settings"] is None else value["settings"]
                        host.lobby.configure(value["save_slot"], settings, command["revision"])
                    elif command["action"] == "create" and host and command["value"] is True:
                        create = getattr(transport, "create_lobby", None)
                        if create is None or steam_lobby != "idle":
                            raise ValueError("Steam lobby creation requires an idle Steam plugin")
                        create()
                        steam_lobby = "creating"
                    elif command["action"] == "invite" and host and command["value"] is True:
                        invite = getattr(transport, "invite_dialog", None)
                        if invite is None or steam_lobby not in (None, "owned"):
                            raise ValueError("Steam invitation control is unavailable")
                        invite()
                    elif command["action"] == "check-load" and host and command["value"] is True:
                        host.lobby.check_load(command["revision"])
                    elif command["action"] == "cancel-load-check" and host and command["value"] is True:
                        host.lobby.cancel_load_check()
                    else:
                        raise ValueError("command is not allowed for this role")
                except (OSError, ValueError) as exc:
                    lobby_files.error = str(exc)
            elif invite_scope is not None:
                try:
                    if command["action"] != "join-invite" or command["value"] is not True:
                        raise ValueError("an explicit Steam invitation confirmation is required")
                    transport.join_invite(command["revision"])
                    steam_lobby, steam_invite = "joining", None
                except (OSError, ValueError) as exc:
                    lobby_files.error = str(exc)
        if host:
            lobby_message = host.lobby.snapshot()
            if host.ready and (now >= next_lobby
                               or lobby_message != (lobby_files.last_status or {}).get("lobby")):
                transport.send(lobby_message)
                next_lobby = now + LOBBY_INTERVAL
        elif lobby_message is not None:
            if now >= next_load_ack:
                ack = guest.lobby.load_ack(load_source)
                if ack is not None:
                    transport.send(ack)
                next_load_ack = now + CHECK_INTERVAL
            lobby_message = guest.lobby.current_message()
            if lobby_message is None:
                local_save_matches = None
        lobby_files.publish(lobby_message, link_ready and lobby_message is not None, role,
                            catalog=save_catalog.view if host and save_catalog is not None else None,
                            local_save_matches=local_save_matches, steam_lobby=steam_lobby,
                            steam_invite=steam_invite if invite_scope is not None else None,
                            steam_membership=steam_membership)

    def disconnect(output):
        nonlocal epoch, last_sample, last_contact, next_retry
        if epoch is not None:
            if host:
                host.reset_link()
            else:
                # A local pipe break does not identify a different remote host.
                guest.reset_link()
            output.disconnect()
            if lobby_files:
                lobby_files.publish(host.lobby.snapshot() if host else None, False, role, steam_lobby=steam_lobby)
        epoch = last_sample = None
        last_contact = next_retry = 0.0

    with (PoseFile(data / "re2_coop_guest_pose.json", remote_id, local_clock_lease=True) as output,
          lobby_files if lobby_files is not None else nullcontext()):
        update_lobby(time.monotonic())
        while stop is None or not stop.is_set():
            now = time.monotonic()
            try:
                payload = transport.receive()
            except OSError:
                disconnect(output)
                update_lobby(time.monotonic())
                time.sleep(0.1)
                continue
            if transport.role is not None and transport.role != role:
                raise ValueError("Python bridge role does not match the RE2 Steam lobby role")
            if transport.epoch is None or steam_lobby == "leaving":
                disconnect(output)
                update_lobby(now)
                time.sleep(0.05)
                continue
            if transport.epoch != epoch:
                disconnect(output)
                # A peer epoch can change after the last lobby poll. Bind the
                # new link to the current lobby before processing any payload.
                if host and membership_revision is not None:
                    revision = membership_revision()
                    if revision is None and host.membership_revision is not None:
                        update_lobby(now)
                        time.sleep(0.05)
                        continue
                    host.bind_membership(revision)
                epoch = transport.epoch
                last_contact = now
            if now - last_contact >= PEER_TIMEOUT:
                if host:
                    host.reset_link()
                else:
                    # Keep the outstanding hello request while waiting for its
                    # snapshot. Responses may be queued behind older traffic.
                    if guest.ready:
                        guest.reset_link()
                    next_retry = 0.0
                output.disconnect()
                last_sample = None
                last_contact = now

            try:
                if host:
                    expired = host.expire_poses()
                    if expired and host.ready:
                        for event in expired:
                            transport.send(event)
                        output.update(host.state)
                message = v1.decode(payload, steam_pose=True) if payload is not None else None
                if message and host:
                    response = host.receive(message, now=time.time())
                    if response is not None:
                        transport.send(response)
                        last_contact = now
                        if response["type"] in ("event", "snapshot"):
                            output.update(host.state)
                elif message and guest:
                    was_ready = guest.ready
                    if guest.receive(message):
                        if message["type"] != "lobby_state":
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

                update_lobby(now)

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
                            proposal = make_proposal(local_id, sample)
                            proposal["session_id"] = guest.replica.session_id
                            transport.send(proposal)
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
    parser.add_argument("--lobby", action="store_true", help="exchange lobby metadata and terminal commands")
    parser.add_argument("--lobby-save-slot", help="host's slot identifier; does not load an RE2 save")
    parser.add_argument("--save-catalog", action="store_true", help="use the local native scenario-save catalog")
    parser.add_argument("--allow-save-date", help="limit catalog selection to one engine calendar date (YYYY-MM-DD)")
    parser.add_argument("--load-save-directory", type=Path,
                        help="opt in to read-only shared file comparison using this native win64_save directory")
    args = parser.parse_args()
    if args.lobby_save_slot is not None and (not args.lobby or args.role != "host"):
        parser.error("--lobby-save-slot requires --lobby and the host role")
    if (args.save_catalog and not args.lobby
            or args.allow_save_date is not None and not (args.save_catalog or args.load_save_directory)):
        parser.error("--save-catalog requires --lobby; --allow-save-date requires a local native catalog")
    if args.load_save_directory is not None and (not args.lobby or args.allow_save_date is None
                                                or args.role == "host" and not args.save_catalog):
        parser.error("--load-save-directory requires --lobby, --allow-save-date and the host --save-catalog")
    if sys.platform != "win32":
        parser.error("the RE2 Steam plugin requires Windows")
    if (not args.data.is_dir() or not 0 < args.pid <= 0xffffffff
            or args.host_id == args.guest_id):
        parser.error("expected an existing data directory, a process ID and distinct player IDs")
    try:
        validate_player_id(args.host_id)
        validate_player_id(args.guest_id)
        catalog = (SaveCatalog(args.data / "re2_coop_save_catalog.json", allow_date=args.allow_save_date)
                   if args.save_catalog else None)
        load_source = (NativeSaveSource(args.data, args.load_save_directory, allow_date=args.allow_save_date)
                       if args.load_save_directory is not None else None)
        with lock_data_directory(args.data):
            run_bridge(args.data, SteamPipe(args.pid), b"H" if args.role == "host" else b"G",
                       args.host_id, args.guest_id, lobby_enabled=args.lobby,
                       lobby_config={"save_slot": args.lobby_save_slot} if args.role == "host" else None,
                       save_catalog=catalog, load_source=load_source)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        print(f"Steam pose bridge stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
