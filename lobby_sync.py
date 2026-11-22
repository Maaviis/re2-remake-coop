"""Host-owned lobby metadata on the verified Steam pose link."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import secrets

from load_preflight import ACK_LEASE, CHECK_INTERVAL, TOKEN, validate_ack, validate_check
from session import Lobby
from save_catalog import reference_identity_digest, validate_reference
from sync_model import state_digest


MAX_INTEGER = 2**53 - 1
GUEST_LOBBY_LEASE = 3.0


def validate_choices(slot, settings):
    if slot is not None and (not isinstance(slot, str) or not 0 < len(slot) <= 128):
        raise ValueError("invalid lobby save slot")
    if not isinstance(settings, dict) or any(not isinstance(key, str) for key in settings):
        raise ValueError("invalid lobby settings")
    if len(json.dumps(settings, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 512:
        raise ValueError("lobby settings exceed the byte limit")


def validate_state(data):
    fields = {"host_id", "guest_id", "save_slot", "settings", "revision", "connected", "ready"}
    if not isinstance(data, dict) or not fields <= data.keys() or data.keys() - fields - {"save_ref", "load_check"}:
        raise ValueError("invalid lobby state fields")
    host, guest = data["host_id"], data["guest_id"]
    if any(not isinstance(player, str) or not 0 < len(player) <= 128 for player in (host, guest)) or host == guest:
        raise ValueError("invalid lobby players")
    validate_choices(data["save_slot"], data["settings"])
    if type(data["revision"]) is not int or not 0 <= data["revision"] <= MAX_INTEGER:
        raise ValueError("invalid lobby revision")
    if type(data["connected"]) is not bool:
        raise ValueError("invalid lobby connection")
    ready = data["ready"]
    if not isinstance(ready, dict) or set(ready) != {host, guest} or any(type(v) is not bool for v in ready.values()):
        raise ValueError("invalid lobby readiness")
    if not data["connected"] and any(ready.values()):
        raise ValueError("disconnected lobby cannot be ready")
    if "save_ref" in data:
        reference = data["save_ref"]
        if isinstance(reference, dict) and set(reference) == {"available"} and reference["available"] is False:
            if any(ready.values()):
                raise ValueError("unavailable save cannot be ready")
        else:
            validate_reference(data["save_ref"])
            if data["save_slot"] != f"scenario:{data['save_ref']['slot_id']}":
                raise ValueError("save reference does not match the selected slot")
    if "load_check" in data:
        validate_check(data["load_check"], revision=data["revision"], eligible=data["connected"]
                       and all(ready.values()) and data.get("save_ref", {}).get("available") is True)


class LobbyHost:
    def __init__(self, session_id, host_id, guest_id, *, save_slot=None, settings=None, catalog=None,
                 load_source=None):
        validate_choices(save_slot, settings or {})
        if catalog is not None and {"campaign", "difficulty"} & (settings or {}).keys():
            raise ValueError("campaign and difficulty belong to the selected RE2 save")
        self.catalog = catalog
        self.save_ref = None
        self.session_id = session_id
        self.guest_id = guest_id
        self.lobby = Lobby(host_id)
        if save_slot is not None:
            self.lobby.select_save(host_id, save_slot)
        self.lobby.configure(host_id, **deepcopy(settings or {}))
        self.sequence = 0
        self.last_state = None
        if load_source is not None and catalog is None:
            raise ValueError("shared load preflight requires the native catalog")
        self.load_source = load_source
        self.load_check = None
        self._check_deadline = self._next_source_check = 0.0
        self._ack_sequence = 0
        self._guest_stage = None
        self._guest_campaign_revision = None

    def connect(self):
        if self.lobby.guest_id is None:
            self.lobby.join(self.guest_id)
        else:
            self.lobby.reconnect(self.guest_id)

    def disconnect(self):
        self.lobby.disconnect()

    def configure(self, slot, settings, revision):
        self._refresh_save()
        if revision != self.lobby.revision or type(revision) is not int:
            raise ValueError("lobby configuration requires the current revision")
        validate_choices(slot, settings)
        if slot is None:
            raise ValueError("save slot required")
        if self.catalog:
            if {"campaign", "difficulty"} & settings.keys():
                raise ValueError("campaign and difficulty belong to the selected RE2 save")
            self.catalog.select(slot)
        self.lobby.select_save(self.lobby.host_id, slot)
        self.lobby.configure(self.lobby.host_id, **deepcopy(settings))
        self._refresh_save()

    def set_ready(self, player_id, value, revision, *, save_identity=None, campaign_consent=False):
        self._refresh_save()
        if self.catalog is not None and value is True:
            if self.save_ref is None:
                raise ValueError("select an available RE2 save before readiness")
            if player_id == self.guest_id and save_identity != reference_identity_digest(self.save_ref):
                raise ValueError("matching guest RE2 save required")
        if not self.lobby.connected:
            raise ValueError("lobby peer is disconnected")
        self.lobby.set_ready(player_id, value, revision)
        if player_id == self.guest_id:
            self._guest_campaign_revision = revision if value and campaign_consent is True else None

    def campaign_ready(self):
        return (self.load_source is not None and self.save_ref is not None and self.lobby.connected
                and all(self.lobby.ready.values()) and self._guest_campaign_revision == self.lobby.revision)

    def snapshot(self):
        self._refresh_save()
        self._refresh_load()
        lobby = self.lobby
        data = {"host_id": lobby.host_id, "guest_id": self.guest_id,
                "save_slot": lobby.save_slot, "settings": deepcopy(lobby.settings),
                "revision": lobby.revision, "connected": lobby.connected,
                "ready": {lobby.host_id: lobby.ready[lobby.host_id],
                          self.guest_id: lobby.ready.get(self.guest_id, False)}}
        if self.catalog is not None:
            data["save_ref"] = deepcopy(self.save_ref) if self.save_ref is not None else {"available": False}
        if self.load_source is not None:
            data["load_check"] = deepcopy(self.load_check)
        validate_state(data)
        if data != self.last_state:
            self.sequence += 1
            self.last_state = deepcopy(data)
        return {"version": 1, "type": "lobby_state", "session_id": self.session_id,
                "sequence": self.sequence, "digest": state_digest(data), "data": data}

    def check_load(self, revision, *, start_campaign=False):
        self._refresh_save()
        if (self.load_source is None or type(revision) is not int or revision != self.lobby.revision
                or self.save_ref is None or not self.lobby.connected or not all(self.lobby.ready.values())):
            raise ValueError("shared load check requires both ready players and the current native selection")
        if start_campaign and not self.campaign_ready():
            raise ValueError("guest campaign consent is required for the current save selection")
        try:
            fingerprint = self.load_source.fingerprint(self.save_ref)
        except (OSError, ValueError):
            self._fail_check("local_source_unavailable")
            raise
        now = time.monotonic()
        self.load_check = {"attempt_id": secrets.token_hex(16), "revision": revision, "admission": 1,
                           "save_digest": fingerprint, "phase": "checking", "reason": ""}
        if start_campaign:
            self.load_check["campaign_start"] = True
        self._check_deadline, self._next_source_check, self._ack_sequence = now + ACK_LEASE, now + CHECK_INTERVAL, 0
        self._guest_stage = None

    def cancel_load_check(self):
        if self.load_check is not None:
            self._fail_check("cancelled")

    def _fail_check(self, reason):
        if self.load_check is not None and (self.load_check["phase"] != "failed" or reason == "cancelled"):
            self.load_check.pop("start", None)
            self.load_check.update(phase="failed", reason=reason)

    def _refresh_load(self):
        check = self.load_check
        if check is None or check["phase"] == "failed":
            return
        if check.get("campaign_start") is True and self._guest_campaign_revision != check["revision"]:
            self._fail_check("cancelled")
            return
        if (not self.lobby.connected or not all(self.lobby.ready.values()) or self.save_ref is None
                or self.lobby.revision != check["revision"]):
            self._fail_check("selection_changed")
            return
        now = time.monotonic()
        if now >= self._check_deadline:
            self._fail_check("start_window_expired" if check["phase"] == "starting" else "guest_ack_expired")
        elif check["phase"] != "starting" and now >= self._next_source_check:
            self._next_source_check = now + CHECK_INTERVAL
            try:
                fingerprint = self.load_source.fingerprint(self.save_ref)
            except (OSError, ValueError):
                self._fail_check("local_source_unavailable")
            else:
                if time.monotonic() >= self._check_deadline:
                    self._fail_check("guest_ack_expired")
                elif fingerprint != check["save_digest"]:
                    self._fail_check("local_file_changed")

    def acknowledge_load(self, message):
        validate_ack(message)
        self._refresh_save()
        self._refresh_load()
        check = self.load_check
        if (check is None or check["phase"] not in ("checking", "prepared") or message["session_id"] != self.session_id
                or message["revision"] != check["revision"] or message["attempt_id"] != check["attempt_id"]
                or message["sequence"] <= self._ack_sequence):
            return False
        now = time.monotonic()
        if now >= self._check_deadline:
            self._fail_check("guest_ack_expired")
            return False
        self._ack_sequence = message["sequence"]
        if not message["accepted"]:
            self._fail_check("guest_source_unavailable")
        elif message["save_digest"] != check["save_digest"]:
            self._fail_check("guest_file_mismatch")
        else:
            check["phase"] = "prepared"
            self._check_deadline = now + ACK_LEASE
            self._guest_stage = message.get("stage_id")
        return True

    def begin_start(self, local_stage):
        if (not isinstance(local_stage, str) or not TOKEN.fullmatch(local_stage)
                or self._guest_stage is None or local_stage == self._guest_stage):
            return False
        self._refresh_save()
        self._refresh_load()
        check = self.load_check
        if check is None or check["phase"] != "prepared":
            return False
        check.update(phase="starting", start={"H": local_stage, "G": self._guest_stage,
                                              "guest_ack_sequence": self._ack_sequence})
        return True

    def start_deadline(self):
        if self.load_check is not None and self.load_check["phase"] == "starting":
            return self._check_deadline

    def _refresh_save(self):
        if self.catalog is None:
            return
        view = self.catalog.snapshot()
        if (self.load_check is not None and self.load_check["phase"] == "starting"
                and view["reason"] == "save_service_busy"):
            return
        reference = next((entry["reference"] for entry in view["entries"]
                          if entry["key"] == self.lobby.save_slot), None)
        if reference != self.save_ref:
            self.save_ref = reference
            self.lobby._advance_revision()


class LobbyGuest:
    def __init__(self, host_id, guest_id, *, catalog=None):
        self.host_id, self.guest_id = host_id, guest_id
        self.catalog = catalog
        self.message = None
        self._received_at = None
        self._ack_attempt = None
        self._ack_sequence = 0
        self._stage_acks = {}
        self._start_withdrawn = None

    def reset_link(self):
        self.message = self._received_at = None
        self._stage_acks.clear()
        self._start_withdrawn = None

    def receive(self, message, session_id):
        validate_state(message["data"])
        data = message["data"]
        if (message["session_id"] != session_id or data["host_id"] != self.host_id
                or data["guest_id"] != self.guest_id or not data["connected"]
                or state_digest(data) != message["digest"]):
            return False
        previous = self.message
        if previous and previous["session_id"] == session_id:
            if message["sequence"] < previous["sequence"]:
                return False
            if message["sequence"] == previous["sequence"] and message != previous:
                return False
            if data["revision"] < previous["data"]["revision"]:
                return False
        self.message = deepcopy(message)
        self._received_at = time.monotonic()
        return True

    def current_message(self):
        if self._received_at is None or time.monotonic() - self._received_at >= GUEST_LOBBY_LEASE:
            return None
        return self.message

    def matching_save_identity(self):
        state = self.current_message()
        if self.catalog is None or state is None:
            return None
        data = state["data"]
        reference = data.get("save_ref")
        if not reference or not reference["available"]:
            return None
        try:
            local_identity = reference_identity_digest(self.catalog.select(data["save_slot"]))
        except ValueError:
            return None
        if self.current_message() is not state:
            return None
        return local_identity if local_identity == reference_identity_digest(reference) else None

    def ready_message(self, value, *, campaign_consent=False):
        # A withdrawal can target the last verified revision after its lease expires.
        state = self.current_message() if value is True else self.message
        if state is None or type(value) is not bool:
            raise ValueError("verified lobby and boolean readiness required")
        data = state["data"]
        message = {"version": 1, "type": "lobby_ready", "session_id": state["session_id"],
                   "revision": data["revision"], "value": value}
        if value and "save_ref" in data:
            if not data["save_ref"]["available"]:
                raise ValueError("host save is unavailable")
            identity = self.matching_save_identity()
            if identity is None:
                raise ValueError("matching local RE2 save required")
            message["save_identity"] = identity
            if campaign_consent:
                message["campaign_consent"] = True
        if value:
            self._start_withdrawn = None
        else:
            self._start_withdrawn = (state["session_id"], data["revision"])
            self._stage_acks.clear()
        return message

    def load_ack(self, source, *, stage_id=None):
        state = self.current_message()
        if state is None or source is None:
            return None
        data = state["data"]
        check = data.get("load_check")
        if check is None or check["phase"] not in ("checking", "prepared"):
            return None
        attempt = (state["session_id"], check["attempt_id"])
        if attempt != self._ack_attempt:
            self._ack_attempt, self._ack_sequence = attempt, 0
            self._stage_acks.clear()
        try:
            fingerprint = source.fingerprint(data["save_ref"])
        except (OSError, ValueError):
            fingerprint = None
        if self.current_message() is not state or self._ack_sequence >= MAX_INTEGER:
            return None
        self._ack_sequence += 1
        message = {"version": 1, "type": "lobby_load_ack", "session_id": state["session_id"],
                "revision": check["revision"], "attempt_id": check["attempt_id"],
                "sequence": self._ack_sequence, "save_digest": fingerprint, "accepted": fingerprint is not None}
        if (stage_id is not None and fingerprint is not None and check.get("admission") == 1
                and check["phase"] == "prepared" and self._start_withdrawn != (state["session_id"], data["revision"])):
            now = time.monotonic()
            self._stage_acks = {seq: proof for seq, proof in self._stage_acks.items() if now < proof[1]}
            if len(self._stage_acks) < 64:
                self._stage_acks[self._ack_sequence] = stage_id, now + ACK_LEASE
                message["stage_id"] = stage_id
        return message

    def start_deadline(self, message, stage_id):
        if self.current_message() is not message or message is None:
            return None
        check = message["data"].get("load_check")
        if (not check or check["phase"] != "starting" or check["start"]["G"] != stage_id
                or self._ack_attempt != (message["session_id"], check["attempt_id"])):
            return None
        proof = self._stage_acks.get(check["start"]["guest_ack_sequence"])
        # The guest's own send time precedes host receipt, so this cutoff
        # cannot be moved forward by a delayed or repeated start decision.
        if proof is not None and proof[0] == stage_id:
            deadline = min(proof[1], self._received_at + GUEST_LOBBY_LEASE)
            if time.monotonic() < deadline:
                return deadline
        return None


def write_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8",
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
    try:
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


class LobbyFiles:
    def __init__(self, data, *, game_pid=None):
        self.status_path = data / "re2_coop_lobby.json"
        self.command_path = data / "re2_coop_lobby_command.json"
        self.game_pid = game_pid
        self.last_command = None
        self.error = None
        self.last_status = None
        self.next_write = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.last_status is not None:
            stopped_steam = "unavailable" if "steam_lobby" in self.last_status else None
            self.publish(self.last_status["lobby"], False, self.last_status["role"].encode("ascii"),
                         steam_lobby=stopped_steam)

    def publish(self, message, connected, role, *, catalog=None, local_save_matches=None,
                steam_lobby=None, steam_invite=None, steam_membership=None, prepared_start=None,
                campaign_start_supported=False, campaign_start_ready=False, campaign_setup=None,
                campaign_setup_status=None):
        value = {"schema": 1, "role": role.decode("ascii"), "connected": connected,
                 "lobby": message, "error": self.error, "catalog": catalog}
        if self.game_pid is not None:
            value["game_pid"] = self.game_pid
        if local_save_matches is not None:
            value["local_save_matches"] = local_save_matches
        if steam_lobby is not None:
            value["steam_lobby"] = steam_lobby
        if steam_invite is not None:
            value["steam_invite"] = steam_invite
        if steam_membership is not None:
            value["steam_membership"] = steam_membership
        if prepared_start is not None:
            value["prepared_start"] = prepared_start
        if campaign_setup is not None:
            value["campaign_setup"] = campaign_setup
        if campaign_setup_status is not None:
            value["campaign_setup_status"] = campaign_setup_status
        if campaign_start_supported:
            value["campaign_start_supported"] = True
            value["campaign_start_ready"] = campaign_start_ready
        if value != self.last_status or time.monotonic() >= self.next_write:
            write_json(self.status_path, {**value, "written_at": int(time.time())})
            self.last_status = deepcopy(value)
            self.next_write = time.monotonic() + 1

    def revoke_prepared_start(self):
        if self.last_status is not None and "prepared_start" in self.last_status:
            value = {key: part for key, part in self.last_status.items() if key != "prepared_start"}
            write_json(self.status_path, {**value, "written_at": int(time.time())})
            self.last_status = value

    def command(self, scope, *, steam_membership=None, campaign_setup=None):
        try:
            if self.command_path.stat().st_size > 2048:
                return None
            value = json.loads(self.command_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(value, dict) or value.get("id") == self.last_command:
            return None
        self.last_command = value.get("id")
        self.error = None
        action = value.get("action")
        target = steam_membership if action == "leave" else campaign_setup if action == "prepare-campaign" else scope
        if (target is None or set(value) != {"id", "written_at", "session_id", "revision", "action", "value"}
                or not isinstance(value["id"], str) or not 0 < len(value["id"]) <= 128
                or type(value["written_at"]) is not int or not 0 <= time.time() - value["written_at"] <= 5
                or value["session_id"] != target["session_id"] or type(value["revision"]) is not int
                or value["revision"] != target["revision"]):
            self.error = "command expired or lobby changed"
            return None
        return value
