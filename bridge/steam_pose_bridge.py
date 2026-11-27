"""Run the host-authoritative pose bridge over the local RE2 Steam plugin."""

import argparse
from collections import deque
from threading import Lock
from contextlib import nullcontext
import math
from pathlib import Path
import secrets
import sys
import time
from coop_diagnostics import SessionDiagnostics
from session_replay import SceneRecorder

from guest_equipment_link import GuestEquipmentLink, MAGIC as EQUIPMENT_MAGIC
from guest_pose import FLOAT32_MAX, PoseFile, validate_player_id
from campaign_setup import steam_save_from_local
from checkpoint_archive_link import CheckpointArchiveLink
from lobby_sync import LobbyFiles, LobbyGuest, LobbyHost, checkpoint_scope, remove_status_file, write_json
from load_preflight import CHECK_INTERVAL, NativeSaveSource, read_staged_load
from load_witness import _read_json
from observer import MAX_OBSERVATION_AGE, player_proposal, read_sample, valid_campaign_area, valid_campaign_attempt, valid_motion
from pose_bridge import lock_data_directory
from protocol import v1
from save_catalog import SaveCatalog
from save_protection import active_save_identity, storage_guard_active
from sync_model import Host, Replica, state_digest


MAX_PAYLOAD = 4096
PIPE_HEADER_SIZE = 9
PIPE_REPLY_LIMIT = MAX_PAYLOAD + PIPE_HEADER_SIZE
POSE_BATCH_LIMIT = 4
RETRY_INTERVAL = 1
PEER_TIMEOUT = 5
MAX_RETIRED_RUNS = 256
LOBBY_INTERVAL = 1

# Only these status codes cross the link. Native errors can contain private paths.
def _guest_prepare_failure(exc):
    return {
        "Steam konnte den aktiven RE2-Spielstandordner nicht bestimmen.": "save_directory",
        "exclusive coop save directory unavailable": "save_directory",
        "Eine aktive geschuetzte RE2-Spielstandkopie ist erforderlich.": "save_protection",
        "Einzelspieler-Dateien konnten nicht gesperrt werden. Offene Speicherzugriffe prüfen.": "save_protection",
        "RE2 hat den geschuetzten Kampagnenstart nicht bestaetigt.": "native_start_unconfirmed",
        "RE2 hat den Speicherschutz im freien Titelmenü noch nicht bestätigt. Koop-Ordner erneut vorbereiten.": "native_start_unconfirmed",
        "Die bestehende Kampagne ist noch aktiv. Im Titelmenü die Lobby verlassen und neu öffnen.": "native_start_unconfirmed",
    }.get(str(exc), "guest_error")


class _LobbyRoleChanged(Exception):
    pass


class _CampaignPrepared(Exception):
    pass


def _native_lobby_role(status):
    if status in ("invite-pending", "joining", "verifying", "canceling", "joined"):
        return b"G"
    if status in ("idle", "creating", "owned"):
        return b"H"
    return None


def envelope(kind, **fields):
    return {"version": v1.VERSION, "type": kind, **fields}


class CutsceneLink:
    """Poll the opposite Lua runtime using this side's clock and a single-use challenge."""

    def __init__(self, data, pid, role):
        self.local_file = data / "re2_coop_cutscene_local.json"
        self.peer_file = data / "re2_coop_cutscene_peer.json"
        self.pid, self.role = pid, role.decode()
        self.scope = self.pending = self.peer = self.last_view = None
        self.live = False
        self.next_poll = 0
        self.history_scope = self.last_scene = None
        self.last_by_event = {}
        self.recorder = SceneRecorder(data) if role == b'H' else None
        self.recorded_local = None
        self.next_local_read = 0

    def clear(self):
        if self.recorder is not None:
            self.recorder.close("scope_closed")
            self.recorder.key = None
        self.recorded_local = None
        self.next_local_read = 0
        self.scope = self.pending = self.peer = self.last_view = None
        self.live = False
        self.next_poll = 0
        remove_status_file(self.peer_file)

    def bind(self, scope, live):
        if scope is not None and scope == self.scope and live and not self.live:
            # While waiting we publish only peer=null and issue no challenges.
            # RE2 may have the file open without Windows delete sharing.
            self.live = True
            return
        if scope != self.scope or live != self.live:
            self.clear()
            self.scope, self.live = scope, live
        if scope is not None and self.history_scope != scope:
            self.history_scope, self.last_scene = scope, None
            self.last_by_event.clear()

    def _advance(self, state):
        """A prior scene, phase, or superseded vote cannot become current again."""
        if state is None:
            return False
        event, occurrence = state["event"], state["occurrence"]
        previous = self.last_scene
        if previous and (event, occurrence) == (previous["event"], previous["occurrence"]):
            order = ("waiting", "playing", "ended")
            if (order.index(state["phase"]) < order.index(previous["phase"]) or state["vote"] < previous["vote"]
                    or state["vote"] == previous["vote"] and previous["decision"] in ("accept", "decline")
                    and state["decision"] != previous["decision"]):
                return False
        else:
            seen = self.last_by_event.get(event)
            if seen is not None and occurrence <= seen["occurrence"]:
                # The guest can put an unplayed scene aside to follow host order.
                # Its next arrival reuses that occurrence number, with a fresh reply.
                if (occurrence != seen["occurrence"] or self.role != "H"
                        or seen["phase"] != "waiting" or seen["vote"] != 0):
                    return False
        self.last_by_event[event] = self.last_scene = state
        return True

    def _local(self, wall):
        try:
            observation = _read_json(self.local_file, max_bytes=2048)
            if (not isinstance(observation, dict)
                    or observation.keys() != v1.CUTSCENE_FIELDS | {"schema", "at", "game_pid", "attempt_id"}
                    or type(observation.get("schema")) is not int
                    or observation["schema"] != 1 or type(observation.get("game_pid")) is not int
                    or observation["game_pid"] != self.pid or observation.get("attempt_id") != self.scope["attempt_id"]
                    or type(observation.get("at")) is not int or not 0 <= wall - observation["at"] <= 2):
                return None, 0
            state = {key: observation[key] for key in v1.CUTSCENE_FIELDS}
            v1.check_cutscene_state(state)
            return state, wall - observation["at"]
        except (OSError, ValueError, KeyError, RecursionError):
            return None, 0

    def tick(self, transport, message, now, wall):
        if self.scope is None:
            return
        # Never stamp a delayed reply as a new observation. The local poll
        # preceded the remote read, and the remote reports its Lua sample age.
        if self.pending and now - self.pending[1] >= 1.5:
            self.pending = None
        if (self.live and message and message["role"] != self.role
                and all(message[key] == value for key, value in self.scope.items())):
            if message["type"] == "cutscene_poll":
                state, age = self._local(wall)
                self.recorded_local, self.next_local_read = state, now + .5
                transport.send(envelope("cutscene_reply", **self.scope, role=self.role,
                                        challenge=message["challenge"], state=state, age=age))
            elif self.pending and message["challenge"] == self.pending[0]:
                _, sent, stamp = self.pending
                self.pending = None
                age = message["age"]
                self.peer = ((message["state"], stamp - age, sent + 2 - age)
                             if now < sent + 2 - age and self._advance(message["state"]) else None)
        if self.peer and (now >= self.peer[2] or not 0 <= wall - self.peer[1] <= 2):
            self.peer = None
        view = {"schema": 1, "game_pid": self.pid, "role": self.role, "attempt_id": self.scope["attempt_id"],
                "at": self.peer[1] if self.peer else wall, "peer": self.peer[0] if self.peer else None}
        # A buffered receive can predate a native epoch change. SteamPipe.send
        # verifies the epoch with the plugin before publishing a new Lua lease.
        new_lease = self.peer is not None and view != self.last_view
        if self.live and self.pending is None and (new_lease or now >= self.next_poll):
            self.pending = (secrets.token_hex(16), now, wall)
            transport.send(envelope("cutscene_poll", **self.scope, role=self.role, challenge=self.pending[0]))
            self.next_poll = now + .25
        if view != self.last_view:
            write_json(self.peer_file, view)
            self.last_view = view
        if self.recorder is not None and self.live:
            # Guest polls normally provide the local sample. Keep observing the
            # host during a missing guest reply without renewing the guest lease.
            if now >= self.next_local_read:
                self.recorded_local, _ = self._local(wall)
                self.next_local_read = now + .5
            self.recorder.observe(self.scope, self.recorded_local, view["peer"], now)


def _active_cutscene_guard(data, scope, stage_id, selection, binding):
    try:
        guard = _read_json(data / "re2_coop_save_guard.json")
    except (ValueError, OSError, RecursionError):
        return False
    if not isinstance(guard, dict):
        return False
    scope = {**scope, "guard_run_id": guard.get("guard_run_id")}
    stamp = guard.get("at")
    hold = guard.get("load_hold")
    return (type(stamp) is int and 0 <= time.time() - stamp <= 3 and guard.get("active") is True
            and guard.get("schema") == 1 and guard.get("hooks") == 26
            and guard.get("allowed_load_calls") == 0 and guard.get("denied_loads") == 0
            and guard.get("writes") in (None, {}) and state_digest(scope)[:32] == stage_id
            and guard.get("protection_active") is True and guard.get("protection") == binding
            and guard.get("campaign_mount_ready") == binding["campaign_namespace"]
            and guard.get("policy_id") == guard.get("load_request_id") == stage_id
            and guard.get("load_error") == "" and guard.get("command_error") == ""
            and guard.get("prepared_load") == {"scope": scope, "new_game": selection}
            and guard.get("load_phase") in ("closing_menu", "loading", "scene_loaded")
            and (guard["load_phase"] != "scene_loaded" or guard.get("in_title") is False)
            and isinstance(hold, dict) and hold.get("load_request_id") == stage_id
            and hold.get("phase") in ("waiting_for_scene", "requesting", "held", "releasing", "released"))


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
    if not required <= value.keys() or value.keys() - required - {"motion", "campaign_attempt_id", "campaign_area"}:
        return False
    stamp, sequence, run = (value[key] for key in ("observed_at", "observer_sequence", "observer_run_id"))
    if (type(stamp) is not int or not 0 < stamp <= v1.MAX_SAFE_INTEGER
            or (now is not None and not 0 <= now - stamp <= MAX_OBSERVATION_AGE)
            or type(sequence) is not int or not 1 <= sequence <= v1.MAX_SAFE_INTEGER
            or not isinstance(run, str) or not 0 < len(run) <= 128
            or type(value["tdb"]) is not int or value["tdb"] != 70):
        return False
    if value["position"] is None or value["rotation"] is None:
        return (value["position"] is value["rotation"] is None
                and not value.keys() & {"motion", "campaign_attempt_id", "campaign_area"})
    return (_vectors(value, "position", 3) and _vectors(value, "rotation", 4)
            and math.hypot(*value["rotation"]) > 0
            and ("motion" not in value or valid_motion(value["motion"]))
            and ("campaign_attempt_id" not in value or valid_campaign_attempt(value["campaign_attempt_id"]))
            and ("campaign_area" not in value or ("campaign_attempt_id" in value
                                                  and valid_campaign_area(value["campaign_area"]))))


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
            settings = dict(self.lobby.lobby.settings)
            settings.pop('coop_checkpoint', None)
            config = {"save_slot": self.lobby.lobby.save_slot, "settings": settings,
                      "catalog": self.lobby.catalog, "load_source": self.lobby.load_source}
        self._start_session(config)
        return True

    def reset_link(self):
        self.ready = False
        self._clear_pose(self.guest_id)
        self._clear_campaign_poses()
        if self.lobby:
            self.lobby.disconnect()

    def _clear_campaign_poses(self):
        for player, pose in tuple(self.state.state["players"].items()):
            if "campaign_attempt_id" in pose:
                self._clear_pose(player)

    def _clear_pose(self, player):
        if player not in self.pose_deadlines:
            return None
        previous = self.state.state["players"][player]
        cleared = {**previous, "position": None, "rotation": None}
        cleared.pop("motion", None)
        cleared.pop("campaign_attempt_id", None)
        cleared.pop("campaign_area", None)
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
        if message["type"] == "pose_resync":
            if (self.ready and self.lobby_request_id == message["request_id"]
                    and self.state.session_id == message["session_id"]):
                return envelope("snapshot", data=self.state.snapshot(), request_id=message["challenge"])
            return None
        if message["type"] == "hello":
            self.expire_poses()
            self.ready = True
            if self.lobby:
                if self.lobby_request_id != message["request_id"]:
                    self._clear_campaign_poses()
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
                                         save_identity=message.get("save_identity"),
                                         new_game_identity=message.get("new_game_identity"),
                                         checkpoint_identity=message.get("checkpoint_identity"),
                                         campaign_consent=message.get("campaign_consent", False))
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
        self.joined_request_id = None
        self.resync_request = None
        self.resync_sequence = 0
        self.resync_deadline = 0.0
        self.lobby.reset_link()

    def hello(self):
        if self.request_id is None:
            self.request_id = secrets.token_hex(16)
        return envelope("hello", request_id=self.request_id)

    def receive(self, message, *, recover_gap=False):
        try:
            if self.ready and message["type"] == "lobby_state":
                return self.lobby.receive(message, self.replica.session_id)
            if message["type"] == "snapshot":
                recovering = self.ready and self.resync_request is not None
                expected = self.resync_request["challenge"] if recovering else self.request_id
                if (self.ready and not recovering) or expected is None or expected != message.get("request_id"):
                    return False
                snapshot = message["data"]
                if recovering and (snapshot["session_id"] != self.replica.session_id
                                   or snapshot["sequence"] < self.resync_sequence):
                    return False
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
                if recovering:
                    self.resync_request = None
                else:
                    self.joined_request_id = self.request_id
                    self.request_id = None
                self.ready = True
                return True
            if self.ready and message["type"] == "event":
                event = message["data"]
                if (event["kind"] != "player" or event["target"] not in self.players
                        or not _valid_pose(event["value"])):
                    raise ValueError("unexpected event")
                if self.resync_request is not None:
                    if event["session_id"] != self.replica.session_id:
                        raise ValueError("pose session changed during resync")
                    return False
                if (recover_gap and self.joined_request_id and event["session_id"] == self.replica.session_id
                        and event["sequence"] > self.replica.sequence + 1):
                    self.resync_request = envelope("pose_resync", session_id=self.replica.session_id,
                                                   request_id=self.joined_request_id, challenge=secrets.token_hex(16))
                    self.resync_sequence = event["sequence"]
                    self.resync_deadline = time.monotonic() + PEER_TIMEOUT
                    return False
                return self.replica.apply(event)
        except ValueError:
            self.resync_request = None
            self.ready = False
        return False


def _read(path):
    try:
        sample = read_sample(path, require_fresh=True)
    except (OSError, ValueError):
        return None
    return sample if "observed_at" in sample else None

def _interrupted_pipe(exc):
    # Each request opens a local named-pipe instance. A closed instance
    # does not report the Steam peer's identity or membership.
    return isinstance(exc, TimeoutError) or getattr(exc, 'winerror', None) in (109, 121, 231, 232, 233)


class SteamPipe:
    # The plugin has one command-pipe instance per game. All bridge threads
    # in this process (including temporary SteamPipe objects) share it.
    _lobby_request_lock = Lock()

    def __init__(self, pid, *, stream="pose", batch_reads=False):
        if stream not in ("pose", "snapshot", "combat"):
            raise ValueError("invalid RE2 Steam stream")
        self.game_pid = pid
        self.name = rf"\\.\pipe\re2-coop-steam-{stream}-{pid}"
        self.lobby_name = rf"\\.\pipe\re2-coop-steam-lobby-{pid}"
        self.epoch = None
        self.role = None
        self._batch_reads = batch_reads and stream == "pose"
        self._pending_poses = deque()

    def request(self, data, *, pipe_name=None):
        if pipe_name == self.lobby_name:
            with self._lobby_request_lock:
                if data in (b"status", b"membership-revision", b"cloud-status", b"user-data-folder"):
                    try:
                        return self._request(data, pipe_name=pipe_name)
                    except OSError as exc:
                        if not _interrupted_pipe(exc):
                            raise
                return self._request(data, pipe_name=pipe_name)
        return self._request(data, pipe_name=pipe_name)

    def _request(self, data, *, pipe_name=None):
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
            for operation, argument in ((win.WriteFile, data), (win.ReadFile, PIPE_REPLY_LIMIT)):
                pending, error = operation(handle, argument, overlapped=True)
                if (error == win.ERROR_IO_PENDING
                        and win.WaitForSingleObject(pending.event, 1000) != win.WAIT_OBJECT_0):
                    pending.cancel()
                    pending.GetOverlappedResult(True)
                    raise TimeoutError("RE2 pipe reply timed out")
                count, error = pending.GetOverlappedResult(True)
                if error:
                    raise OSError(0, "RE2 pipe I/O failed", None, error)
                if operation == win.WriteFile and count != len(data):
                    raise OSError("RE2 pipe request was not fully written")
            return pending.getbuffer()
        finally:
            win.CloseHandle(handle)

    def receive(self):
        if self._pending_poses:
            return self._pending_poses.popleft()
        if self._batch_reads:
            reply = self.request(b"B")
            if reply == b"E":
                # Older plugins reject the batch command when a peer is active.
                self._batch_reads = False
                reply = self.request(b"R")
            elif reply.startswith(b"B"):
                return self._receive_batch(reply)
        else:
            reply = self.request(b"R")
        if reply == b"N":
            self.role = self.epoch = None
            return None
        scene = reply.startswith(b"C")
        if scene:
            reply = reply[1:]
        if len(reply) < PIPE_HEADER_SIZE or reply[:1] not in (b"H", b"G"):
            raise OSError("invalid RE2 pose pipe response")
        self.role, self.epoch = reply[:1], reply[1:PIPE_HEADER_SIZE]
        if scene:
            # The unordered channel only carries renewable polls and replies.
            try:
                message = v1.decode(reply[PIPE_HEADER_SIZE:], steam_pose=True)
            except v1.ProtocolError:
                return None
            if message["type"] not in ("cutscene_poll", "cutscene_reply"):
                return None
        return reply[PIPE_HEADER_SIZE:] or None

    def _receive_batch(self, reply):
        header_size = 1 + PIPE_HEADER_SIZE
        error = "invalid RE2 pose pipe batch"
        role = reply[1:2]
        if not header_size < len(reply) <= PIPE_REPLY_LIMIT or role not in (b"H", b"G"):
            raise OSError(error)
        frames = []
        offset = header_size
        while offset < len(reply):
            size = int.from_bytes(reply[offset:offset + 2], "big")
            offset += 2
            if not 0 < size <= len(reply) - offset or len(frames) == POSE_BATCH_LIMIT:
                raise OSError(error)
            frames.append(reply[offset:offset + size])
            offset += size
        self.role, self.epoch = role, reply[2:header_size]
        self._pending_poses.extend(frames)
        return self._pending_poses.popleft()

    def send(self, message):
        self.send_payload(_encode(message), diagnostic=message["type"] in ("coop_log", "coop_log_ack"),
                          scene=message["type"] in ("cutscene_poll", "cutscene_reply"))

    def send_payload(self, payload, *, diagnostic=False, scene=False):
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PAYLOAD:
            raise ValueError("invalid RE2 Steam payload")
        try:
            command = b"C" if scene else b"S"
            response = self.request(command + self.epoch + payload) if self.epoch is not None else None
            if scene and response == b"D":
                return  # The epoch matched. A fresh challenge will retry this dropped datagram.
            if response != b"S":
                raise OSError("RE2 Steam send failed or the peer changed")
        except OSError:
            if not diagnostic:
                self._pending_poses.clear()
            raise

    def _lobby_action(self, command, fallback):
        reply = self.request(command, pipe_name=self.lobby_name)
        if reply == b"error return to the RE2 window and retry this command":
            raise ValueError("Zum RE2-Fenster zurückkehren und die Aktion erneut wählen.")
        if reply.startswith(b"error "):
            raise ValueError(reply[6:].decode("ascii", errors="replace"))
        if reply != b"accepted " + command.split()[0]:
            raise ValueError(fallback)

    def invite_dialog(self):
        self._lobby_action(b"invite-dialog", "Steam invitation unavailable; check the owned Steam lobby")

    def lobby_status(self):
        try:
            status = self.request(b"status", pipe_name=self.lobby_name).decode("ascii")
        except (OSError, UnicodeError):
            return "unavailable"
        if status in {"idle", "owned", "creating", "invite-pending", "joining", "verifying",
                      "joined", "leaving", "canceling"}:
            return status
        return "unavailable"

    def cloud_status(self):
        try:
            status = self.request(b"cloud-status", pipe_name=self.lobby_name).decode("ascii")
        except (OSError, UnicodeError):
            return "cloud-unavailable"
        if status in {"cloud-enabled", "cloud-app-disabled", "cloud-account-disabled"}:
            return status
        return "cloud-unavailable"

    def save_directory(self):
        prefix = b"user-data-folder "
        try:
            reply = self.request(b"user-data-folder", pipe_name=self.lobby_name)
            if not reply.startswith(prefix) or b"\0" in reply:
                return None
            data_folder = Path(reply[len(prefix):].decode("utf-8"))
        except (OSError, UnicodeError):
            return None
        return steam_save_from_local(data_folder)

    def protect_campaign(self):
        self._lobby_action(b"protect-campaign", "Steam campaign protection was not confirmed")

    def preparation_window_active(self):
        try:
            reply = self.request(b"prepare-context", pipe_name=self.lobby_name)
        except OSError:
            return None
        if reply == b"frame":
            return True
        if reply == b"background":
            return False
        return None

    def prepare_new_game(self, revision, token):
        if (type(revision) is not int or not 0 < revision <= 0xffffffff or
                not isinstance(token, str) or not v1.REQUEST_ID.fullmatch(token)):
            raise ValueError("Ungültige Kampagnenbindung.")
        self._lobby_action(f"prepare-new-game {revision} {token}".encode("ascii"),
                           "RE2 hat den Koop-Speicherordner nicht freigegeben.")

    def current_campaign(self, revision):
        if type(revision) is not int or not 0 < revision <= 0xffffffff:
            raise ValueError("Die Steam-Lobby hat sich geändert.")
        reply = self.request(f"current-campaign {revision}".encode("ascii"), pipe_name=self.lobby_name)
        if reply == b"none":
            return None
        token = reply.decode("ascii", errors="replace")
        if not v1.REQUEST_ID.fullmatch(token):
            raise ValueError("Kampagnenbindung der Steam-Lobby nicht verfügbar. Auf beiden PCs den gleichen Build prüfen.")
        return token

    def revoke_new_game(self, token):
        if isinstance(token, str) and v1.REQUEST_ID.fullmatch(token):
            self._lobby_action(b"revoke-new-game " + token.encode("ascii"),
                               "Die Schreibfreigabe konnte nicht zurückgenommen werden.")

    def create_lobby(self):
        if self.lobby_status() != "idle":
            raise ValueError("Steam lobby creation requires an idle Steam plugin")
        self._lobby_action(b"create", "Steam lobby creation rejected by the native plugin")

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
        self._lobby_action(command, "Steam invitation changed or the lobby is busy")

    def join_error(self, revision):
        try:
            reply = self.request(f"join-error {revision}".encode("ascii"), pipe_name=self.lobby_name)
        except OSError:
            return None
        prefix = b"join-failed "
        return reply[len(prefix):].decode("ascii", errors="replace") if reply.startswith(prefix) else None

    def leave_lobby(self, revision):
        command = f"leave {revision}".encode("ascii")
        self._lobby_action(command, "Steam lobby membership changed")
        self._pending_poses.clear()


def run_bridge(data, transport, role, host_id, guest_id, *, stop=None, lobby_config=None,
               lobby_enabled=False, save_catalog=None, load_source=None, automatic_role=False,
               stage_campaign=None, enable_campaign=None, campaign_setup_status=None,
               previous_command_id=None, last_link_loss=None, prepare_new_campaign=None,
               exchange_checkpoint=None):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack
    from readonly_save_control import read_active_guard

    if save_catalog is not None and not lobby_enabled:
        raise ValueError("native save catalog requires the lobby")
    if load_source is not None and (not lobby_enabled or role == b"H" and save_catalog is None):
        raise ValueError("shared load preflight requires the lobby and the host native catalog")
    if load_source is not None and role == b"G" and save_catalog is None:
        save_catalog = load_source.catalog
    if stage_campaign is not None and load_source is None:
        raise ValueError("campaign start requires a protected local save source")
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
    outstanding_pings = {}
    lobby_files = (LobbyFiles(data, game_pid=getattr(transport, "game_pid", None), last_link_loss=last_link_loss)
                   if lobby_enabled else None)
    if lobby_files is not None:
        lobby_files.last_command = previous_command_id
    next_lobby = 0.0
    next_load_ack = 0.0
    guest_ready_sent = None
    steam_status = getattr(transport, "lobby_status", None) if lobby_files else None
    invite_revision = getattr(transport, "invite_revision", None) if guest and steam_status else None
    join_error = getattr(transport, "join_error", None) if guest and steam_status else None
    membership_revision = getattr(transport, "membership_revision", None) if host or steam_status else None
    steam_session = secrets.token_hex(16) if steam_status else None
    steam_invite = steam_membership = None
    joining_revision = None
    steam_lobby, next_steam_status = None, 0.0
    stage_binding, cached_stage, next_stage_check = None, None, 0.0
    handled_campaign = None
    campaign_request = None
    new_game_in_progress = None
    campaign_link = None
    peer_capability = None
    peer_new_game = None
    supports_new_game = getattr(stage_campaign, "supports_new_game", False) is True
    original_catalog = save_catalog
    preparation = prepared_revision = None
    preparation_revision = None
    host_prepare_generation = 0
    guest_prepare_attempt = None
    guest_failure = "guest_error"
    guest_prepare_receipt = None
    direct_link = None
    revocations = set()
    peer_campaign_seen = peer_new_seen = float('-inf')
    scenes = CutsceneLink(data, getattr(transport, "game_pid", None), role) if prepare_new_campaign else None
    equipment = GuestEquipmentLink(data, getattr(transport, "game_pid", None), role) if prepare_new_campaign else None
    diagnostics = (SessionDiagnostics(data, transport.game_pid, role.decode(), lobby_files.source_commit)
                   if lobby_files and type(getattr(transport, "game_pid", None)) is int else None)
    if diagnostics:
        lobby_files.on_error = diagnostics.error
    scene_stage = None
    next_scene_guard = 0.0
    checkpoint_controller = checkpoint_binding = checkpoint_request_seen = None
    checkpoint_grant = None
    pending_new_membership = None

    def close_checkpoint():
        if checkpoint_controller is not None:
            checkpoint_controller.close()

    def current_source():
        if checkpoint_controller is not None and checkpoint_binding is not None:
            return checkpoint_controller.source
        return load_source

    def update_checkpoint(message, now):
        nonlocal checkpoint_controller, checkpoint_binding, checkpoint_request_seen, campaign_request, campaign_link
        nonlocal checkpoint_grant
        scope = archive_link.scope
        if checkpoint_controller is not None and (scope is None or scope != checkpoint_binding):
            if campaign_request == checkpoint_request_seen:
                campaign_request = None
            checkpoint_controller.cancel()
            checkpoint_binding = checkpoint_request_seen = checkpoint_grant = None
            if checkpoint_controller.finished:
                checkpoint_controller.close()
                checkpoint_controller = None
        choice = message['data']['settings'].get('coop_checkpoint') if message else None
        lobby = host.lobby if host else guest.lobby
        lobby.checkpoint_proof = None
        if host:
            lobby.load_source = load_source
        archive_link.local_prepared = False
        if not choice:
            return None
        check = message['data'].get('load_check') or {}
        attempt = (message['session_id'], check.get('attempt_id'))
        if (check.get('phase') == 'failed' and handled_campaign == attempt and
                not (check.get('reason') == 'start_window_expired' and checkpoint_grant == attempt)):
            archive_link.fail('Checkpoint-Start abgebrochen. Der Host kann den Spielstand erneut wählen.')
        if checkpoint_binding is not None and checkpoint_controller.error:
            archive_link.fail(checkpoint_controller.error)
        if archive_link.error:
            if checkpoint_controller is not None:
                checkpoint_controller.cancel()
                if campaign_request == checkpoint_request_seen:
                    campaign_request = None
            lobby_files.error = archive_link.error
            return 'failed'
        if not scope or archive_link.peer_nonce is None:
            return 'negotiating'
        if not archive_link.transferred or checkpoint_controller and checkpoint_binding is None:
            return 'transfer'
        if checkpoint_controller is None:
            from checkpoint_start import CheckpointStartController
            checkpoint_controller = CheckpointStartController(data, transport.game_pid, role, stop, choice,
                                                              steam_membership['revision'])
            checkpoint_binding = scope
            checkpoint_controller.start()
        request = checkpoint_controller.request_id
        if request and checkpoint_request_seen != request:
            checkpoint_request_seen = campaign_request = request
            campaign_link = ready_request()
        admitted = (request and handled_campaign == attempt
                    and (check.get('phase') == 'starting' or check.get('reason') == 'start_window_expired'))
        if not (checkpoint_controller.ready or admitted):
            return 'preparing'
        archive_link.local_prepared = True
        if host:
            lobby.load_source = checkpoint_controller.source
        lobby.checkpoint_proof = checkpoint_scope(message['data']['revision'], choice)
        return 'ready' if archive_link.peer_prepared(now) else 'waiting_peer'

    def bind_source(source, stage):
        nonlocal load_source, stage_campaign, save_catalog, supports_new_game, next_capability, peer_new_game
        load_source, stage_campaign = source, stage
        save_catalog = source.catalog if source is not None else original_catalog
        supports_new_game = getattr(stage, "supports_new_game", False) is True
        next_capability = 0.0
        peer_new_game = None
        if host:
            host.lobby.catalog, host.lobby.load_source = save_catalog, source
        else:
            guest.lobby.catalog = save_catalog
    next_capability = 0.0

    def begin_direct():
        nonlocal preparation, preparation_revision, direct_link, guest_failure
        guest_failure = "guest_error"
        preparation_revision = steam_membership["revision"]
        link = ready_request()
        direct_link = link if link[1] is not None else None
        preparation = pool.submit(prepare_new_campaign, preparation_revision)

    def guest_prepare_state(message, link):
        nonlocal guest_prepare_attempt
        generation = message["prepare_generation"]
        if message["package_commit"] != lobby_files.source_commit:
            return "package_mismatch"
        if stage_campaign is not None:
            return None
        if archive_link.scope or archive_link.busy or checkpoint_controller is not None:
            return 'preparing'
        if not steam_membership or revocations:
            return "bridge_unavailable"
        scope = (link, steam_membership["revision"])
        if preparation is not None:
            return "preparing"
        if guest_prepare_attempt and guest_prepare_attempt[0] == scope and generation <= guest_prepare_attempt[1]:
            return guest_failure
        if steam_status() != "joined" or transport.membership_revision() != steam_membership["revision"]:
            return "bridge_unavailable"
        foreground = transport.preparation_window_active()
        if foreground is not True:
            return "guest_window" if foreground is False else "bridge_unavailable"
        cloud = transport.cloud_status()
        if cloud not in ("cloud-account-disabled", "cloud-app-disabled"):
            return "cloud_enabled" if cloud == "cloud-enabled" else "cloud_unavailable"
        guest_prepare_attempt = (scope, generation)
        lobby_files.error = None
        begin_direct()
        return "preparing"

    def invalidate_direct(reason, cause, exc=None):
        nonlocal preparation_revision, prepared_revision, stage_binding, cached_stage, direct_link
        nonlocal campaign_request, new_game_in_progress, handled_campaign, guest_ready_sent
        if preparation is None and prepared_revision is None:
            return
        if diagnostics:
            diagnostics.note("GUARD", "binding_withdrawn=" + cause)
        if preparation_revision is not None or prepared_revision is not None:
            evidence = {"schema": 1, "at": int(time.time()), "game_pid": getattr(transport, 'game_pid', None),
                        "role": role.decode(), "cause": cause, "membership_revision": prepared_revision or preparation_revision,
                        "attempt_id": scene_stage[1] if scene_stage else None}
            if cause == 'handshake_changed' and direct_link is not None:
                current = ready_request()
                evidence.update(link_ready=current[1] is not None, same_session=current[0] == direct_link[0],
                                same_join=current[1] == direct_link[1])
            if exc is not None:
                trace = exc.__traceback__
                while trace.tb_next is not None:
                    trace = trace.tb_next
                evidence.update(check=trace.tb_frame.f_code.co_name, line=trace.tb_lineno,
                                system_code=getattr(exc, 'winerror', None))
            try:
                write_json(data / 're2_coop_campaign_binding_loss.json', evidence)
            except OSError:
                pass
        if scenes is not None:
            scenes.clear()
        preparation_revision = None  # A running worker still owns its eventual result.
        direct_link = None
        if prepared_revision is not None:
            revocations.add(load_source.campaign_binding['campaign_namespace'])
            prepared_revision = None
            bind_source(None, None)
        stage_binding = cached_stage = campaign_request = new_game_in_progress = handled_campaign = None
        guest_ready_sent = None
        lobby_files.revoke_prepared_start()
        if host:
            host.lobby.cancel_load_check()
        lobby_files.action_failed(ValueError(reason))

    def revoke_outstanding():
        for token in tuple(revocations):
            try:
                transport.revoke_new_game(token)
            except (OSError, ValueError) as exc:
                lobby_files.action_failed(exc)
            else:
                revocations.remove(token)

    def validate_direct(source, revision):
        binding = source.campaign_binding
        directory = source.supplied_directory
        if (not revision or transport.membership_revision() != revision
                or transport.lobby_status() != ('owned' if host else 'joined')
                or transport.cloud_status() not in ('cloud-app-disabled', 'cloud-account-disabled')
                or not storage_guard_active(directory)):
            raise ValueError('Steam-Lobby oder Spielstandschutz der neuen Kampagne ist abgelaufen.')
        active_save_identity(transport, directory)
        guard = read_active_guard(data, protected=True, runtime_directory=directory)
        if (binding['game_pid'] != transport.game_pid or guard['protection'] != binding
                or guard.get('campaign_mount_ready') != binding['campaign_namespace']):
            raise ValueError('Der Koop-Speicherordner ist nicht mehr freigegeben.')

    def finish_direct():
        # Role changes and ordinary exits must also collect a grant made by a
        # worker after its caller departed. Preparation has bounded native waits.
        if preparation is not None:
            try:
                source, _ = preparation.result()
            except (OSError, ValueError):
                pass
            else:
                revocations.add(source.campaign_binding['campaign_namespace'])
        if prepared_revision is not None:
            revocations.add(load_source.campaign_binding['campaign_namespace'])
        for retry in range(3):
            revoke_outstanding()
            if not revocations:
                break
            if retry < 2:
                time.sleep(.1)

    def ready_request():
        if host and host.ready:
            return host.state.session_id, host.lobby_request_id
        if guest and guest.ready:
            return guest.replica.session_id, guest.joined_request_id
        return None, None

    def peer_supports_campaign():
        return (peer_capability is not None and peer_capability == ready_request()
                and time.monotonic() - peer_campaign_seen < PEER_TIMEOUT)

    def local_stage(message):
        nonlocal stage_binding, cached_stage, next_stage_check
        source = current_source()
        if source is None or steam_membership is None or not message:
            stage_binding, cached_stage = None, None
            return None
        binding = (message["session_id"], message["sequence"], steam_membership)
        now = time.monotonic()
        if binding != stage_binding or now >= next_stage_check:
            stage_binding, cached_stage, next_stage_check = binding, None, now + CHECK_INTERVAL
            stage = read_staged_load(data, message, role.decode("ascii"), lobby_files.game_pid, steam_membership)
            if stage is not None:
                try:
                    if (transport.membership_revision() == steam_membership["revision"]
                            and transport.cloud_status() in ("cloud-app-disabled", "cloud-account-disabled")
                            and storage_guard_active(source.supplied_directory)
                            and active_save_identity(transport, source.supplied_directory)
                            == active_save_identity(transport, source.directory)):
                        cached_stage = stage
                except (OSError, ValueError):
                    pass
        if cached_stage and message['data']['settings'].get('coop_checkpoint'):
            releasing = message['data']['load_check']['phase'] == 'starting'
            if not checkpoint_controller or not checkpoint_controller.staged(cached_stage, releasing=releasing):
                return None
        return cached_stage

    def update_lobby(now, *, refresh_native=False, archive_packet=None):
        nonlocal pending_new_membership, checkpoint_grant
        nonlocal preparation, preparation_revision, prepared_revision, guest_failure
        nonlocal next_lobby, next_load_ack, guest_ready_sent, steam_lobby, next_steam_status
        nonlocal steam_invite, steam_membership, joining_revision, handled_campaign, campaign_request, new_game_in_progress
        nonlocal campaign_link, direct_link, host_prepare_generation, next_capability
        nonlocal scene_stage, next_scene_guard
        if steam_status is not None and (refresh_native or now >= next_steam_status):
            previous_steam_lobby, steam_lobby = steam_lobby, steam_status()
            next_steam_status = now + 1.0
            native_role = _native_lobby_role(steam_lobby) if automatic_role else None
            if native_role is not None and native_role != role:
                raise _LobbyRoleChanged(native_role)
            if guest and (joining_revision is not None or previous_steam_lobby in ("joining", "verifying", "canceling")):
                if steam_lobby in ("idle", "invite-pending"):
                    reason = join_error(joining_revision) if join_error and joining_revision is not None else None
                    lobby_files.error = reason or "Steam did not confirm the lobby join"
                    joining_revision = None
                elif steam_lobby == "joined":
                    joining_revision = None
            revision = invite_revision() if invite_revision and steam_lobby == "invite-pending" else None
            steam_invite = {"session_id": steam_session, "revision": revision} if revision else None
            expected_membership = "owned" if host else "joined"
            revision = (membership_revision()
                        if membership_revision and steam_lobby == expected_membership else None)
            steam_membership = {"session_id": steam_session, "revision": revision} if revision else None
            if preparation_revision is not None and revision != preparation_revision:
                invalidate_direct('Die Steam-Lobby hat sich während der Vorbereitung geändert.', 'membership_changed')
            if prepared_revision is not None:
                try:
                    validate_direct(load_source, prepared_revision)
                except (OSError, ValueError) as exc:
                    invalidate_direct(str(exc), 'direct_validation_failed', exc)
            revoke_outstanding()
            if host and host.bind_membership(revision):
                disconnect(output, "steam_membership_changed")
        if lobby_files is None:
            return
        if preparation_revision is not None or prepared_revision is not None:
            link = ready_request()
            if direct_link is not None and link != direct_link:
                invalidate_direct('Die Verbindung zum Koop-Partner hat sich geändert.', 'handshake_changed')
                revoke_outstanding()
            elif link[1] is not None:
                direct_link = link
        if preparation is not None and preparation.done():
            revision, future = preparation_revision, preparation
            preparation_revision = preparation = None
            try:
                source, stage = future.result()
            except (OSError, ValueError) as exc:
                guest_failure = _guest_prepare_failure(exc)
                lobby_files.action_failed(exc)
            else:
                try:
                    validate_direct(source, revision)
                except (OSError, ValueError) as exc:
                    guest_failure = _guest_prepare_failure(exc)
                    revocations.add(source.campaign_binding['campaign_namespace'])
                    revoke_outstanding()
                    lobby_files.action_failed(exc)
                else:
                    bind_source(source, stage)
                    prepared_revision = revision
        if campaign_link != ready_request():
            campaign_request = new_game_in_progress = None
        if campaign_request is not None or new_game_in_progress is not None:
            try:
                guard = _read_json(data / 're2_coop_save_guard.json')
            except (OSError, ValueError):
                guard = {}
            stamp = guard.get('at') if isinstance(guard, dict) else None
            protection = guard.get('protection') if isinstance(guard, dict) else None
            if (type(stamp) is int and 0 <= time.time() - stamp <= 3
                    and isinstance(protection, dict) and protection.get('game_pid') == lobby_files.game_pid
                    and guard.get('command_id') == (campaign_request or new_game_in_progress)):
                error = guard.get('command_error')
                if new_game_in_progress and guard.get('load_request_id') == new_game_in_progress:
                    if guard.get('load_phase') == 'failed':
                        error = guard.get('load_error') or 'new_game_transition_failed'
                    hold = guard.get('load_hold')
                    hold = hold if isinstance(hold, dict) else {}
                    if hold.get('phase') in ('failed', 'lost', 'resume_failed'):
                        error = hold.get('reason') or 'native_pause_failed'
                    elif hold.get('phase') == 'released' and hold.get('native_phase') == 'released':
                        new_game_in_progress = None
                if error:
                    lobby_files.error = 'Kampagnenstart: ' + str(error)
                    campaign_request = None
                    new_game_in_progress = None
                    if host:
                        host.lobby.cancel_load_check()
                    elif guest_ready_sent is not None and guest.lobby.message:
                        transport.send(guest.lobby.ready_message(False))
                        guest_ready_sent = None
                elif campaign_request and guard.get('load_request_id') == campaign_request and guard.get('load_phase') in (
                        'reading_save', 'closing_menu', 'loading', 'scene_loaded'):
                    write_json(data / 're2_coop_lobby_view.json', {
                        'schema': 1, 'id': secrets.token_hex(16), 'at': int(time.time()), 'visible': False})
                    campaign_request = None
        link_ready = host.ready if host else guest.ready
        campaign_ready = stage_campaign is not None and peer_supports_campaign()
        new_game_supported = (campaign_ready and peer_new_game == ready_request() and supports_new_game
                              and now - peer_new_seen < PEER_TIMEOUT)
        guest_preparation = None
        if host and prepared_revision and host_prepare_generation and link_ready and not new_game_supported:
            guest_preparation = "awaiting_reply"
        if (guest_prepare_receipt and guest_prepare_receipt[0] == ready_request()
                and now - guest_prepare_receipt[2] < PEER_TIMEOUT
                and (guest and not stage_campaign or guest_preparation and guest_prepare_receipt[1] == host_prepare_generation)):
            guest_preparation = guest_prepare_receipt[3]
        last_guest_lobby = guest.lobby.message if guest and link_ready else None
        lobby_message = host.lobby.snapshot() if host else None
        local_save_matches, guest_revision = None, None
        if last_guest_lobby is not None:
            lobby_message = guest.lobby.current_message()
            guest_revision = (last_guest_lobby["session_id"], last_guest_lobby["data"]["revision"])
        # Let the outgoing workspace worker finish before the next one can
        # acquire the same native mount, even when the namespace is unchanged.
        archive_message = None if preparation is not None else lobby_message
        archive_link.bind(ready_request(), epoch, steam_membership, archive_message)
        if epoch is not None and (checkpoint_controller is None or checkpoint_binding == archive_link.scope):
            archive_link.tick(transport.send, archive_packet, time.monotonic())
        if guest and lobby_message is not None and "save_ref" in lobby_message["data"]:
            local_save_matches = guest.lobby.matching_save_identity() is not None
        checkpoint_status = update_checkpoint(lobby_message, now)
        if pending_new_membership is not None:
            if (pending_new_membership != (steam_membership, ready_request()) or not link_ready or revocations):
                pending_new_membership = None
            elif checkpoint_controller is None and not archive_link.scope and not archive_link.busy:
                pending_new_membership = None
                host_prepare_generation += 1
                next_capability = 0.
                if stage_campaign is None:
                    begin_direct()
        if checkpoint_status:
            campaign_ready = checkpoint_status == 'ready'
            if checkpoint_status == 'failed' and host and host.lobby.lobby.ready.get(local_id):
                host.lobby.set_ready(local_id, False, host.lobby.lobby.revision)
                host.lobby.cancel_load_check()
        if lobby_message is not None and "new_game" in lobby_message["data"]:
            campaign_ready = new_game_supported
        check = lobby_message["data"].get("load_check") if lobby_message is not None else None
        starting = check is not None and check["phase"] == "starting"
        if guest_ready_sent != guest_revision:
            guest_ready_sent = None
        elif (guest_ready_sent is not None and not starting
              and (lobby_message is None or local_save_matches is False or checkpoint_status == 'failed')):
            transport.send(guest.lobby.ready_message(False))
            guest_ready_sent = None
        command_lobby = lobby_message or last_guest_lobby
        invite_scope = steam_invite if command_lobby is None and not link_ready else None
        scope = ({"session_id": command_lobby["session_id"], "revision": command_lobby["data"]["revision"]}
                 if command_lobby is not None else invite_scope)
        campaign_setup = ({"session_id": steam_session, "revision": 1}
                          if enable_campaign is not None and steam_lobby in ("idle", "invite-pending") else None)
        setup_state, setup_error = (campaign_setup_status()
                                    if campaign_setup is not None and campaign_setup_status else (None, None))
        if scope is not None or steam_membership is not None or campaign_setup is not None:
            command = lobby_files.command(scope, steam_membership=steam_membership, campaign_setup=campaign_setup)
        else:
            command = None
        if command is not None and setup_state != "closing":
            if (command["action"] == "leave" or command["action"] == "ready" and command["value"] is False
                    or host and command["action"] in ("configure", "select-new-game", "check-load", "start-campaign", "cancel-load-check")):
                lobby_files.revoke_prepared_start()
            if command["action"] == "prepare-new-campaign":
                if checkpoint_grant is not None:
                    lobby_files.action_failed(ValueError('Der Koop-Spielstand wird bereits geladen oder gespielt.'))
                elif (host and prepare_new_campaign and steam_membership and preparation is None and not revocations
                        and command["value"] is True and steam_status() == "owned"
                        and (stage_campaign is None or prepared_revision == steam_membership["revision"])):
                    if checkpoint_status and link_ready:
                        try:
                            host.lobby.clear_checkpoint()
                        except ValueError as exc:
                            lobby_files.action_failed(exc)
                        else:
                            pending_new_membership = (steam_membership, ready_request())
                    elif not archive_link.busy and checkpoint_controller is None:
                        host_prepare_generation += 1
                        next_capability = 0.0
                        if stage_campaign is None:
                            begin_direct()
                    else:
                        lobby_files.action_failed(ValueError('Die vorherige Vorbereitung wird beendet.'))
                else:
                    lobby_files.action_failed(ValueError("Die neue Kampagne kann in dieser Lobby noch nicht vorbereitet werden."))
            elif command["action"] == "prepare-campaign":
                try:
                    if command["value"] is not True or steam_status() not in ("idle", "invite-pending"):
                        raise ValueError("Die Kampagne muss vor der Lobby vorbereitet werden.")
                    prepared = enable_campaign()
                except (OSError, ValueError) as exc:
                    lobby_files.action_failed(exc)
                else:
                    if prepared is not None:
                        raise _CampaignPrepared(*prepared, command["id"])
                    setup_state = "closing"
                    setup_error = None
            elif command["action"] == "leave":
                try:
                    if command["value"] is not True:
                        raise ValueError("an explicit Steam lobby departure is required")
                    transport.leave_lobby(command["revision"])
                except (OSError, ValueError) as exc:
                    lobby_files.action_failed(exc)
                else:
                    steam_lobby, steam_membership = "leaving", None
                    disconnect(output, "local_leave")
                    lobby_files.publish(host.lobby.snapshot() if host else None, False, role,
                                        steam_lobby=steam_lobby)
                    return
            elif command_lobby is not None:
                try:
                    if lobby_message is None:
                        raise ValueError("guest lobby state expired")
                    if command["action"] == "ready" and type(command["value"]) is bool:
                        if host:
                            if checkpoint_status and command['value'] and not campaign_ready:
                                raise ValueError('Warte auf die Checkpoint-Vorbereitung beider Spieler.')
                            host.lobby.set_ready(local_id, command["value"], command["revision"])
                        elif link_ready:
                            transport.send(guest.lobby.ready_message(command["value"]))
                            guest_ready_sent = guest_revision if command["value"] else None
                    elif (command["action"] == "ready-campaign" and guest and campaign_ready
                          and link_ready and command["value"] is True):
                        transport.send(guest.lobby.ready_message(True, campaign_consent=True))
                        guest_ready_sent = guest_revision
                    elif command["action"] == "select-checkpoint" and host:
                        if steam_lobby != "owned" or not steam_membership:
                            raise ValueError("Zuerst eine private Steam-Lobby erstellen.")
                        if campaign_request or new_game_in_progress or checkpoint_grant is not None:
                            raise ValueError("Die Kampagne wird bereits geladen.")
                        if load_source is not None:
                            guard = read_active_guard(data, protected=True, runtime_directory=load_source.supplied_directory)
                            if guard.get('in_title') is not True or guard.get('has_player') is not False:
                                raise ValueError('Koop-Spielstände können nur im RE2-Titelmenü gewählt werden.')
                        if preparation is not None or pending_new_membership is not None:
                            raise ValueError('Die Vorbereitung der neuen Kampagne läuft noch.')
                        host.lobby.select_checkpoint(transport, command["value"], command["revision"])
                        lobby_files.revoke_prepared_start()
                    elif command["action"] == "select-new-game" and host:
                        if checkpoint_grant is not None:
                            raise ValueError('Der Koop-Spielstand wird bereits geladen oder gespielt.')
                        if not new_game_supported:
                            raise ValueError("Beide Spieler müssen den Neustart mit demselben geschützten Build vorbereiten.")
                        host.lobby.select_new_game(command["value"], command["revision"])
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
                    elif (command["action"] == "start-campaign" and host and campaign_ready
                          and command["value"] is True):
                        check = host.lobby.load_check
                        if check is not None and check["phase"] != "failed":
                            raise ValueError("another load preparation is active")
                        host.lobby.check_load(command["revision"], start_campaign=True)
                    elif command["action"] == "cancel-load-check" and host and command["value"] is True:
                        host.lobby.cancel_load_check()
                    else:
                        raise ValueError("command is not allowed for this role")
                except (OSError, ValueError) as exc:
                    lobby_files.action_failed(exc)
            elif invite_scope is not None:
                try:
                    if command["action"] != "join-invite" or command["value"] is not True:
                        raise ValueError("an explicit Steam invitation confirmation is required")
                    transport.join_invite(command["revision"])
                    joining_revision = command["revision"]
                    steam_lobby, steam_invite = "joining", None
                except (OSError, ValueError) as exc:
                    lobby_files.action_failed(exc)
        if host:
            lobby_message = host.lobby.snapshot()
            if host.ready and host.lobby.begin_start(local_stage(lobby_message)):
                lobby_message = host.lobby.snapshot()
        elif lobby_message is not None:
            if now >= next_load_ack:
                ack = guest.lobby.load_ack(current_source(), stage_id=local_stage(lobby_message))
                if ack is not None:
                    transport.send(ack)
                next_load_ack = now + CHECK_INTERVAL
            lobby_message = guest.lobby.current_message()
            if lobby_message is None:
                local_save_matches = None
        check = lobby_message["data"].get("load_check") if lobby_message is not None else None
        start_id, start_deadline = None, None
        if link_ready and check is not None and check["phase"] == "starting":
            approved = check["start"][role.decode("ascii")]
            stage = local_stage(lobby_message)
            current = host.lobby.snapshot() if host else guest.lobby.current_message()
            if current == lobby_message and stage == approved:
                start_deadline = host.lobby.start_deadline() if host else guest.lobby.start_deadline(current, approved)
                start_id = approved
            lobby_message = current
        if start_deadline is None or time.monotonic() >= start_deadline:
            lobby_files.revoke_prepared_start()
        if host and host.ready and (now >= next_lobby
                                    or lobby_message != (lobby_files.last_status or {}).get("lobby")):
            transport.send(lobby_message)
            next_lobby = now + LOBBY_INTERVAL
            if start_id is not None:
                current = host.lobby.snapshot()
                if current != lobby_message:
                    lobby_message, start_deadline = current, None
        prepared_start = None
        if start_deadline is not None:
            wall_now = time.time()
            # Lua uses integer local wall time. Round the cutoff down so an
            # old local status file cannot authorize beyond the bridge lease.
            before = int(wall_now + start_deadline - time.monotonic())
            if before > int(wall_now):
                prepared_start = {"id": start_id, "before": before}
                if check.get('checkpoint_version') == 1:
                    checkpoint_grant = (lobby_message["session_id"], check["attempt_id"])
        lobby_files.publish(lobby_message, link_ready and lobby_message is not None, role,
                            catalog=save_catalog.view if host and save_catalog is not None else None,
                            local_save_matches=local_save_matches, steam_lobby=steam_lobby,
                            steam_invite=steam_invite if invite_scope is not None else None,
                            steam_membership=steam_membership, prepared_start=prepared_start,
                            campaign_start_supported=stage_campaign is not None or checkpoint_status is not None,
                            checkpoint_status=checkpoint_status,
                            new_game_supported=new_game_supported,
                            campaign_start_ready=bool(campaign_ready and host and host.lobby.campaign_ready()),
                            campaign_peer_supported=campaign_ready if link_ready and stage_campaign else None,
                            campaign_setup=campaign_setup, campaign_setup_status="preparing" if preparation else setup_state,
                            direct_campaign_available=bool(prepare_new_campaign and steam_membership
                                                           and stage_campaign is None and not revocations),
                            direct_campaign_prepared=bool(prepared_revision and supports_new_game),
                            guest_preparation=guest_preparation,
                            campaign_setup_error=setup_error)
        check = lobby_message["data"].get("load_check") if lobby_message is not None else None
        if scenes is not None:
            selection = lobby_message["data"] if lobby_message else {}
            if (prepared_revision and steam_membership and epoch is not None and link_ready and new_game_supported
                    and direct_link == ready_request() and check and check.get("campaign_start") is True
                    and selection.get("new_game") and check["revision"] == selection["revision"]
                    and all(selection["ready"].values()) and (check["phase"] == "starting" or
                        check["phase"] == "failed" and check["reason"] == "start_window_expired")
                    and scene_stage and scene_stage[:2] == (lobby_message["session_id"], check["attempt_id"])):
                scope = {"session_id": direct_link[0], "request_id": direct_link[1],
                         "attempt_id": check["attempt_id"], "package_commit": lobby_files.source_commit}
                live = scenes.live
                if scenes.scope != scope or now >= next_scene_guard:
                    receipt_scope = {"session_id": scope["session_id"], "attempt_id": scope["attempt_id"],
                                     "revision": check["revision"], "save_digest": check["save_digest"],
                                     "game_pid": lobby_files.game_pid, "role": role.decode(), "membership": steam_membership}
                    live = _active_cutscene_guard(data, receipt_scope, scene_stage[2], selection["new_game"],
                                                  load_source.campaign_binding)
                    next_scene_guard = now + .25
                scenes.bind(scope if live or prepared_start else None, live)
            else:
                scenes.bind(None, False)
        if (campaign_ready and link_ready and check and check.get("campaign_start") is True
                and check["phase"] == "prepared" and (host or guest_ready_sent == guest_revision and guest_revision is not None)):
            attempt = (lobby_message["session_id"], check["attempt_id"])
            if attempt != handled_campaign:
                handled_campaign = attempt
                try:
                    selection = lobby_message["data"]
                    if selection['settings'].get('coop_checkpoint'):
                        checkpoint_controller.stage(check['attempt_id'])
                    else:
                        campaign_request = stage_campaign(selection.get("new_game") or selection["save_slot"])
                    campaign_link = ready_request()
                    if "new_game" in selection:
                        new_game_in_progress = campaign_request
                        scene_stage = (*attempt, campaign_request)
                except (OSError, ValueError) as exc:
                    lobby_files.action_failed(exc)
                    if host:
                        host.lobby.cancel_load_check()
                    else:
                        transport.send(guest.lobby.ready_message(False))
                        guest_ready_sent = None

    def record_loss(reason):
        outstanding_pings.clear()
        if diagnostics:
            diagnostics.close(reason)
        if lobby_files:
            lobby_files.last_link_loss.update(reason=reason, at=int(time.time()), role=role.decode("ascii"))

    def local_pipe_gap(exc):
        if not (_interrupted_pipe(exc) and epoch is not None and ready_request()[1] is not None
                and time.monotonic() - last_contact < PEER_TIMEOUT):
            return False
        if lobby_files:
            lobby_files.revoke_prepared_start()
        return True

    def disconnect(output, reason):
        nonlocal epoch, last_sample, last_contact, next_retry
        nonlocal peer_capability, peer_new_game, next_capability
        archive_link.clear()
        if equipment is not None:
            equipment.clear()
        if epoch is not None:
            invalidate_direct('Die Verbindung zur Koop-Kampagne wurde unterbrochen.', reason)
            revoke_outstanding()
            record_loss(reason)
            if lobby_files:
                lobby_files.revoke_prepared_start()
            if host:
                host.reset_link()
            else:
                # A local pipe break does not identify a different remote host.
                guest.reset_link()
            output.disconnect()
            if lobby_files:
                lobby_files.publish(host.lobby.snapshot() if host else None, False, role,
                                    steam_lobby=steam_lobby, steam_membership=steam_membership)
        epoch = last_sample = None
        peer_capability, peer_new_game, next_capability = None, None, 0.0
        last_contact = next_retry = 0.0

    with (PoseFile(data / "re2_coop_guest_pose.json", remote_id, local_clock_lease=True) as output,
          lobby_files if lobby_files is not None else nullcontext(), ExitStack() as lifecycle):
        if diagnostics:
            lifecycle.callback(diagnostics.close)
        archive_pool = lifecycle.enter_context(ThreadPoolExecutor(max_workers=1)) if exchange_checkpoint else None
        archive_link = CheckpointArchiveLink(role, lobby_files.source_commit if lobby_files else None,
                                             exchange_checkpoint, archive_pool)
        lifecycle.callback(archive_link.clear)
        lifecycle.callback(close_checkpoint)
        if prepare_new_campaign:
            scenes.clear()
            pool = lifecycle.enter_context(ThreadPoolExecutor(max_workers=1))
            lifecycle.callback(finish_direct)
            lifecycle.callback(scenes.clear)
        update_lobby(time.monotonic())
        while stop is None or not stop.is_set():
            now = time.monotonic()
            try:
                payload = transport.receive()
                now = time.monotonic()
            except OSError as exc:
                if local_pipe_gap(exc):
                    time.sleep(0.05)
                    continue
                disconnect(output, "pipe_read_timeout" if isinstance(exc, TimeoutError) else "pipe_read_error")
                update_lobby(time.monotonic())
                time.sleep(0.1)
                continue
            if transport.role is not None and transport.role != role:
                if automatic_role:
                    raise _LobbyRoleChanged(transport.role)
                raise ValueError("Python bridge role does not match the RE2 Steam lobby role")
            if transport.epoch is None or steam_lobby == "leaving":
                disconnect(output, "local_leave" if steam_lobby == "leaving" else "native_peer_unavailable")
                update_lobby(now)
                time.sleep(0.05)
                continue
            if transport.epoch != epoch:
                disconnect(output, "native_epoch_changed")
                if steam_status is not None:
                    # Publish the current native membership before exposing any pose from the new link.
                    try:
                        update_lobby(now, refresh_native=True)
                    except OSError:
                        time.sleep(0.05)
                        continue
                    if steam_lobby == "leaving":
                        time.sleep(0.05)
                        continue
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
            recovery_expired = bool(guest and guest.resync_request and now >= guest.resync_deadline)
            if now - last_contact >= PEER_TIMEOUT or recovery_expired:
                if host and host.ready or guest and guest.ready:
                    reason = 'pose_resync_timeout' if recovery_expired else 'peer_heartbeat_timeout'
                    record_loss(reason)
                    invalidate_direct('Der Koop-Partner antwortet nicht mehr.', reason)
                    revoke_outstanding()
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
                peer_capability, peer_new_game, next_capability = None, None, 0.0
                last_contact = now

            try:
                if host:
                    expired = host.expire_poses()
                    if expired and host.ready:
                        for event in expired:
                            transport.send(event)
                        output.update(host.state)
                inventory_packet = payload if payload and payload.startswith(EQUIPMENT_MAGIC) else None
                message = v1.decode(payload, steam_pose=True) if payload and inventory_packet is None else None
                archive_message = None
                if message and message["type"] == "checkpoint_archive":
                    archive_message, message = message, None
                diagnostic_message = None
                if message and message["type"] in ("coop_log", "coop_log_ack"):
                    diagnostic_message, message = message, None
                scene_message = None
                if message and message["type"] in ("cutscene_poll", "cutscene_reply"):
                    scene_message, message = message, None
                if message and message["type"] == "guest_prepare_status":
                    link = (message["session_id"], message["request_id"])
                    if (host and prepared_revision and link == ready_request()
                            and message["prepare_generation"] == host_prepare_generation):
                        guest_prepare_receipt = (link, host_prepare_generation, now, message["state"])
                    message = None
                if message and message["type"] == "new_game_capability":
                    capability = (message["session_id"], message["request_id"])
                    generation = message.get("prepare_generation")
                    if guest and prepare_new_campaign and generation and capability == ready_request():
                        state = guest_prepare_state(message, capability)
                        if state is not None:
                            guest_prepare_receipt = (capability, generation, now, state)
                            transport.send(envelope("guest_prepare_status", session_id=capability[0],
                                                    request_id=capability[1], prepare_generation=generation, state=state))
                    if supports_new_game and capability == ready_request():
                        compatible = (message["start_version"] == 1 if prepared_revision is None else
                                      message["start_version"] == 2 and message["package_commit"] == lobby_files.source_commit)
                        peer_new_game = capability if compatible else None
                        peer_new_seen = now
                    message = None
                if message and message["type"] == "campaign_pose_capability":
                    capability = (message["session_id"], message["request_id"])
                    if ((stage_campaign is not None or checkpoint_binding is not None) and capability == ready_request()
                            and message.get("resume_version") == v1.CAMPAIGN_RESUME_VERSION):
                        if peer_capability != capability:
                            last_sample = None
                        peer_capability = capability
                        peer_campaign_seen = now
                    message = None
                if (message and host and message["type"] == "propose"
                        and isinstance(message["value"], dict) and "campaign_attempt_id" in message["value"]
                        and not peer_supports_campaign()):
                    message = None
                if message and host:
                    response = host.receive(message, now=time.time())
                    if response is not None:
                        transport.send(response)
                        last_contact = now
                        if response["type"] in ("event", "snapshot"):
                            output.update(host.state)
                elif message and guest:
                    was_ready = guest.ready
                    was_recovering = guest.resync_request is not None
                    if guest.receive(message, recover_gap=prepared_revision is not None or checkpoint_binding is not None):
                        if message["type"] != "lobby_state":
                            output.update(guest.replica)
                        last_contact = now
                        if message["type"] == "snapshot":
                            # Re-publish after verifying a snapshot following local resync.
                            last_sample = None
                    elif guest.resync_request is not None and not was_recovering:
                        output.disconnect()
                        next_retry = 0.0
                    elif message["type"] == "pong" and guest.ready:
                        deadline = outstanding_pings.pop(message["nonce"], None)
                        if deadline is not None and now < deadline:
                            last_contact = now
                    elif was_ready and not guest.ready:
                        record_loss("guest_resync_required")
                        invalidate_direct('Die Verbindung zum Koop-Host muss neu bestätigt werden.', 'guest_resync_required')
                        revoke_outstanding()
                        output.disconnect()
                        last_sample = None
                        next_retry = 0.0

                if guest and now >= next_retry:
                    if guest.resync_request is not None:
                        transport.send(guest.resync_request)
                    elif guest.ready:
                        outstanding_pings = {n: expiry for n, expiry in outstanding_pings.items() if now < expiry}
                        nonce = nonce % v1.MAX_SAFE_INTEGER + 1
                        transport.send(envelope("ping", nonce=nonce))
                        outstanding_pings[nonce] = now + PEER_TIMEOUT
                    else:
                        transport.send(guest.hello())
                    next_retry = now + RETRY_INTERVAL

                session_id, request_id = ready_request()
                if (stage_campaign is not None or checkpoint_binding is not None) and request_id is not None and now >= next_capability:
                    transport.send(envelope("campaign_pose_capability", session_id=session_id, request_id=request_id,
                                            area_version=1, enemy_version=3,
                                            resume_version=v1.CAMPAIGN_RESUME_VERSION))
                    if supports_new_game and (prepared_revision is None or lobby_files.source_commit):
                        build = {"start_version": 1} if prepared_revision is None else {
                            "start_version": 2, "package_commit": lobby_files.source_commit}
                        if host and prepared_revision and host_prepare_generation:
                            build["prepare_generation"] = host_prepare_generation
                        transport.send(envelope("new_game_capability", session_id=session_id, request_id=request_id,
                                                **build))
                    next_capability = now + RETRY_INTERVAL
                update_lobby(now, archive_packet=archive_message)
                if diagnostics:
                    diagnostics.tick(transport, ready_request(), lobby_files.last_status, diagnostic_message, now)
                if scenes is not None:
                    scenes.tick(transport, scene_message, time.monotonic(), int(time.time()))

                if equipment is not None:
                    equipment.tick(transport, ready_request(), current_source(), inventory_packet)

                sample = _read(path)
                if sample is not None:
                    if "campaign_attempt_id" in sample and not peer_supports_campaign():
                        sample.pop("campaign_attempt_id")
                        sample.pop("campaign_area", None)
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
                payload = None
            except OSError as exc:
                if not local_pipe_gap(exc):
                    disconnect(output, "bridge_io_timeout" if isinstance(exc, TimeoutError) else "bridge_io_error")
                payload = None
            # The host sends events for both players on the same stream.
            # Keep draining while messages are available instead of throttling each read.
            if payload is None:
                time.sleep(0.05)


def run_automatic_bridge(data, transport, host_id, guest_id, *, stop, save_catalog=None,
                         load_source=None, stage_campaign=None, enable_campaign=None,
                         campaign_setup_status=None, prepare_new_campaign=None, exchange_checkpoint=None):
    """Follow the Steam invitation and membership of the owning game process."""
    role = b"H"
    last_link_loss = {}
    previous_command_id = None
    while not stop.is_set():
        try:
            run_bridge(data, transport, role, host_id, guest_id, stop=stop, lobby_enabled=True,
                       save_catalog=save_catalog, automatic_role=True,
                       load_source=load_source, stage_campaign=stage_campaign, enable_campaign=enable_campaign,
                       campaign_setup_status=campaign_setup_status,
                       previous_command_id=previous_command_id, last_link_loss=last_link_loss,
                       prepare_new_campaign=prepare_new_campaign, exchange_checkpoint=exchange_checkpoint)
            return
        except _LobbyRoleChanged as change:
            role = change.args[0]
        except _CampaignPrepared as change:
            load_source, stage_campaign, previous_command_id = change.args
            save_catalog = load_source.catalog
            enable_campaign = None


class _GameProcessExit:
    """Wait on the selected process handle so a reused PID cannot revive the bridge."""

    def __init__(self, pid):
        import _winapi

        self._windows = _winapi
        self._handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, pid)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._windows.CloseHandle(self._handle)

    def is_set(self):
        return self.wait(0)

    def wait(self, timeout):
        milliseconds = max(0, math.ceil(timeout * 1000))
        return self._windows.WaitForSingleObject(self._handle, milliseconds) == self._windows.WAIT_OBJECT_0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="REFramework data directory")
    parser.add_argument("--pid", type=int, required=True, help="RE2 process ID")
    parser.add_argument("--role", choices=("host", "guest", "auto"), required=True)
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
    if args.role == "auto" and (not args.lobby or args.load_save_directory is not None):
        parser.error("automatic Steam roles require --lobby without a protected load directory")
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
        with _GameProcessExit(args.pid) as game_exit, lock_data_directory(args.data):
            pipe = SteamPipe(args.pid, batch_reads=True)
            if args.role == "auto":
                from campaign_setup import CampaignSetup
                from coop_checkpoint import discover_after_launch
                from threading import Thread

                setup = CampaignSetup(args.data, pipe, game_exit) if args.save_catalog else None
                if setup:
                    Thread(target=discover_after_launch, daemon=True,
                           args=(args.data, SteamPipe(args.pid), game_exit)).start()
                run_automatic_bridge(args.data, pipe, args.host_id, args.guest_id, stop=game_exit,
                                     save_catalog=catalog, enable_campaign=setup.enable if setup else None,
                                     prepare_new_campaign=setup.enable_new if setup else None,
                                     exchange_checkpoint=setup.exchange_checkpoint if setup else None,
                                     campaign_setup_status=setup.status if setup else None)
            else:
                run_bridge(args.data, pipe, b"H" if args.role == "host" else b"G",
                           args.host_id, args.guest_id, lobby_enabled=args.lobby,
                           lobby_config={"save_slot": args.lobby_save_slot} if args.role == "host" else None,
                           save_catalog=catalog, load_source=load_source, stop=game_exit)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        if args.role == "auto":
            # Packaged bridges have no console. Persist the failing operation
            # without file paths, Steam IDs, command payloads or credentials.
            trace = exc.__traceback__
            while trace.tb_next is not None:
                trace = trace.tb_next
            code = trace.tb_frame.f_code
            try:
                write_json(args.data / 're2_coop_bridge_failure.json', {
                    'schema': 1, 'game_pid': args.pid, 'at': int(time.time()),
                    'exception': type(exc).__name__, 'system_code': getattr(exc, 'winerror', None),
                    'file': Path(code.co_filename).name, 'function': code.co_name, 'line': trace.tb_lineno})
            except OSError:
                pass
        print(f"Steam pose bridge stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
