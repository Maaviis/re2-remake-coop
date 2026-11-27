"""Reference codec for the proposed version 1 gameplay message envelope."""

import json
import math
import re


VERSION = 1
CAMPAIGN_RESUME_VERSION = 3
MAX_SAFE_INTEGER = 2**53 - 1
MESSAGE_FIELDS = {
    "hello": {"version", "type"},
    "ping": {"version", "type", "nonce"},
    "pong": {"version", "type", "nonce"},
    "propose": {"version", "type", "kind", "target", "value"},
    "event": {"version", "type", "data"},
    "snapshot": {"version", "type", "data"},
    "error": {"version", "type", "message"},
}
EVENT_FIELDS = {"session_id", "sequence", "digest", "kind", "target", "value"}
SNAPSHOT_FIELDS = {"session_id", "sequence", "digest", "state"}
EVENT_KINDS = {
    "player", "enemy", "door", "puzzle", "item", "inventory",
    "flag", "action", "damage", "script", "cutscene",
}
STATE_MAPS = {
    "players", "enemies", "doors", "puzzles", "items", "inventories",
    "flags", "actions", "damage", "scripts",
}
DIGEST = re.compile(r"[0-9a-f]{64}")
REQUEST_ID = re.compile(r"[0-9a-f]{32}")
PREPARE_STATES = ("preparing", "package_mismatch", "guest_window", "cloud_enabled",
                  "cloud_unavailable", "bridge_unavailable", "guest_error", "save_directory",
                  "save_protection", "native_start_unconfirmed")
CUTSCENE_FIELDS = {"event", "occurrence", "phase", "vote", "decision"}
CUTSCENE_SCOPE = {"version", "type", "session_id", "request_id", "package_commit",
                  "attempt_id", "role", "challenge"}


class ProtocolError(ValueError):
    """A message violates the version 1 envelope or JSON contract."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON object key")
        result[key] = value
    return result


def _check_json(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError("JSON object keys must be strings")
            key.encode("utf-8")
            _check_json(item)
    elif isinstance(value, list):
        for item in value:
            _check_json(item)
    elif isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError("JSON numbers must be finite")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ProtocolError("JSON integer exceeds the interoperable range")
    elif value is not None:
        raise ProtocolError("expected a JSON value")


def _check_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise ProtocolError(f"invalid {name} fields")


def _check_event(value):
    kind, target = value["kind"], value["target"]
    if not isinstance(kind, str) or kind not in EVENT_KINDS:
        raise ProtocolError("unknown event kind")
    if kind == "cutscene":
        if target is not None:
            raise ProtocolError("cutscene target must be null")
    elif not isinstance(target, str) or not target:
        raise ProtocolError("event target must be a nonempty string")


def _check_authority(value, minimum_sequence):
    sequence = value["sequence"]
    if type(sequence) is not int or not minimum_sequence <= sequence <= MAX_SAFE_INTEGER:
        raise ProtocolError("invalid sequence")
    if not isinstance(value["session_id"], str) or not value["session_id"]:
        raise ProtocolError("invalid session id")
    if not isinstance(value["digest"], str) or not DIGEST.fullmatch(value["digest"]):
        raise ProtocolError("invalid state digest")


def check_cutscene_state(state):
    _check_fields(state, CUTSCENE_FIELDS, "native cutscene")
    if (not isinstance(state["event"], str) or not re.fullmatch(r"evt_(?:0|[1-9][0-9]{0,19})", state["event"])
            or type(state["occurrence"]) is not int or not 1 <= state["occurrence"] <= MAX_SAFE_INTEGER
            or state["phase"] not in ("waiting", "playing", "ended")
            or type(state["vote"]) is not int or not 0 <= state["vote"] <= MAX_SAFE_INTEGER
            or state["decision"] not in ("none", "request", "accept", "decline")
            or (state["vote"] == 0) != (state["decision"] == "none")):
        raise ProtocolError("invalid native cutscene state")


def _check_message(message, *, steam_pose):
    if not isinstance(message, dict):
        raise ProtocolError("expected a message object")
    version = message.get("version")
    if type(version) is not int or version != VERSION:
        raise ProtocolError("unsupported protocol version")
    kind = message.get("type")
    lobby_fields = {
        "lobby_state": {"version", "type", "session_id", "sequence", "digest", "data"},
        "lobby_ready": {"version", "type", "session_id", "revision", "value"},
        "lobby_load_ack": {"version", "type", "session_id", "revision", "attempt_id", "sequence", "save_digest", "accepted"},
        "campaign_pose_capability": {"version", "type", "session_id", "request_id", "area_version", "enemy_version"},
        "new_game_capability": {"version", "type", "session_id", "request_id", "start_version"},
        "checkpoint_archive": {"version", "type", "archive_version", "session_id", "request_id", "revision",
                               "selection_digest", "package_commit", "role", "nonce", "echo", "counter", "state"},
        "guest_prepare_status": {"version", "type", "session_id", "request_id", "prepare_generation", "state"},
        "coop_log": {"version", "type", "session_id", "request_id", "batch", "records"},
        "coop_log_ack": {"version", "type", "session_id", "request_id", "batch"},
        "cutscene_poll": CUTSCENE_SCOPE,
        "pose_resync": {"version", "type", "session_id", "request_id", "challenge"},
        "cutscene_reply": CUTSCENE_SCOPE | {"state", "age"},
    } if steam_pose else {}
    if not isinstance(kind, str) or kind not in MESSAGE_FIELDS.keys() | lobby_fields.keys():
        raise ProtocolError("unknown message type")
    fields = (MESSAGE_FIELDS | lobby_fields)[kind]
    if steam_pose and kind in ("hello", "snapshot", "campaign_pose_capability", "new_game_capability"):
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ProtocolError("invalid Steam pose request_id")
        fields = fields | {"request_id"}
        if kind == "new_game_capability" and message.get("start_version") == 2:
            fields = fields | {"package_commit"}
            if "prepare_generation" in message:
                generation = message["prepare_generation"]
                if type(generation) is not int or not 0 < generation <= MAX_SAFE_INTEGER:
                    raise ProtocolError("invalid host preparation generation")
                fields = fields | {"prepare_generation"}
        if kind == "campaign_pose_capability" and "resume_version" in message:
            if (type(message["resume_version"]) is not int
                    or message["resume_version"] != CAMPAIGN_RESUME_VERSION):
                raise ProtocolError("unsupported campaign resume version")
            fields = fields | {"resume_version"}
    elif steam_pose and kind == "propose":
        if not isinstance(message.get("session_id"), str) or not message["session_id"]:
            raise ProtocolError("invalid Steam pose session_id")
        fields = fields | {"session_id"}
    elif steam_pose and kind == "lobby_ready":
        for field in ("save_identity", "new_game_identity", "checkpoint_identity"):
            if field not in message:
                continue
            identity = message[field]
            if message.get("value") is not True or not isinstance(identity, str) or not DIGEST.fullmatch(identity):
                raise ProtocolError("invalid lobby save identity")
            fields = fields | {field}
        identities = message.keys() & {"save_identity", "new_game_identity", "checkpoint_identity"}
        if len(identities) > 1:
            raise ProtocolError("ambiguous lobby selection")
        if "campaign_consent" in message:
            if message["campaign_consent"] is not True or not identities:
                raise ProtocolError("campaign consent requires ready native save identity")
            fields = fields | {"campaign_consent"}
    elif steam_pose and kind == "lobby_load_ack" and "stage_id" in message:
        fields = fields | {"stage_id"}
    elif kind == "hello" and message.get("heartbeat") is True:
        fields = fields | {"heartbeat"}
    _check_fields(message, fields, kind)
    _check_json(message)

    if kind in ("coop_log", "coop_log_ack"):
        for key in ("session_id", "request_id"):
            if not isinstance(message[key], str) or not REQUEST_ID.fullmatch(message[key]):
                raise ProtocolError("invalid diagnostic session")
        if type(message["batch"]) is not int or not 1 <= message["batch"] <= MAX_SAFE_INTEGER:
            raise ProtocolError("invalid diagnostic batch")
        if kind == "coop_log":
            rows = message["records"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
                raise ProtocolError("invalid diagnostic records")
            for row in rows:
                if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int
                        or not 0 <= row[0] <= 4102444800000 or not isinstance(row[1], str)
                        or not re.fullmatch(r"[A-Z_]{1,32}", row[1]) or not isinstance(row[2], str)
                        or not re.fullmatch(r"[ -~]{1,220}", row[2])):
                    raise ProtocolError("invalid diagnostic record")
    elif kind == "checkpoint_archive":
        for key in ("session_id", "request_id", "nonce", "echo"):
            if key == "echo" and message[key] is None:
                continue
            if not isinstance(message[key], str) or not REQUEST_ID.fullmatch(message[key]):
                raise ProtocolError("invalid checkpoint archive handshake")
        for key in ("revision", "counter"):
            if type(message[key]) is not int or not 1 <= message[key] <= MAX_SAFE_INTEGER:
                raise ProtocolError("invalid checkpoint archive revision or counter")
        if (type(message["archive_version"]) is not int or message["archive_version"] != 1
                or not isinstance(message["selection_digest"], str) or not DIGEST.fullmatch(message["selection_digest"])
                or not isinstance(message["package_commit"], str) or not re.fullmatch("[0-9a-f]{40}", message["package_commit"])
                or message["role"] not in ("H", "G") or message["state"] not in ("exchange", "prepared", "failed")):
            raise ProtocolError("invalid checkpoint archive capability")
    elif kind == "guest_prepare_status":
        for key in ("session_id", "request_id"):
            if not isinstance(message[key], str) or not REQUEST_ID.fullmatch(message[key]):
                raise ProtocolError("invalid guest preparation scope")
        generation = message["prepare_generation"]
        if (type(generation) is not int or not 0 < generation <= MAX_SAFE_INTEGER
                or message["state"] not in PREPARE_STATES):
            raise ProtocolError("invalid guest preparation status")
    elif kind == "pose_resync":
        for key in ("session_id", "request_id", "challenge"):
            if not isinstance(message[key], str) or not REQUEST_ID.fullmatch(message[key]):
                raise ProtocolError("invalid pose resync scope")
    elif kind in ("cutscene_poll", "cutscene_reply"):
        for key in ("session_id", "request_id", "attempt_id", "challenge"):
            if not isinstance(message[key], str) or not REQUEST_ID.fullmatch(message[key]):
                raise ProtocolError("invalid cutscene scope")
        if (message["role"] not in ("H", "G") or not isinstance(message["package_commit"], str)
                or not re.fullmatch("[0-9a-f]{40}", message["package_commit"])):
            raise ProtocolError("invalid cutscene peer identity")
        if kind == "cutscene_reply":
            if type(message["age"]) is not int or not 0 <= message["age"] <= 2:
                raise ProtocolError("invalid cutscene observation age")
            if message["state"] is not None:
                check_cutscene_state(message["state"])
    elif kind == "lobby_state":
        from lobby_sync import validate_state
        _check_authority(message, 1)
        validate_state(message["data"])
    elif kind == "new_game_capability":
        if (not isinstance(message["session_id"], str) or not 0 < len(message["session_id"]) <= 128
                or type(message["start_version"]) is not int or message["start_version"] not in (1, 2)):
            raise ProtocolError("unsupported new game capability")
        if message["start_version"] == 2 and (not isinstance(message["package_commit"], str)
                or re.fullmatch("[0-9a-f]{40}", message["package_commit"]) is None):
            raise ProtocolError("invalid direct campaign package commit")
    elif kind == "campaign_pose_capability":
        if not isinstance(message["session_id"], str) or not 0 < len(message["session_id"]) <= 128:
            raise ProtocolError("invalid campaign pose session")
        if type(message["area_version"]) is not int or message["area_version"] != 1:
            raise ProtocolError("unsupported campaign pose area version")
        if type(message["enemy_version"]) is not int or message["enemy_version"] != 3:
            raise ProtocolError("unsupported campaign enemy version")
    elif kind == "lobby_load_ack":
        from load_preflight import validate_ack
        validate_ack(message)
    elif kind == "lobby_ready":
        if (not isinstance(message["session_id"], str) or not message["session_id"]
                or type(message["revision"]) is not int
                or not 0 <= message["revision"] <= MAX_SAFE_INTEGER
                or type(message["value"]) is not bool):
            raise ProtocolError("invalid lobby readiness message")
    elif kind in ("ping", "pong"):
        nonce = message["nonce"]
        if type(nonce) is not int or not 1 <= nonce <= MAX_SAFE_INTEGER:
            raise ProtocolError("invalid heartbeat nonce")
    elif kind == "propose":
        _check_event(message)
    elif kind == "event":
        data = message["data"]
        _check_fields(data, EVENT_FIELDS, "event data")
        _check_authority(data, 1)
        _check_event(data)
    elif kind == "snapshot":
        data = message["data"]
        _check_fields(data, SNAPSHOT_FIELDS, "snapshot data")
        _check_authority(data, 0)
        _check_fields(data["state"], STATE_MAPS | {"cutscene"}, "snapshot state")
        for name in STATE_MAPS:
            table = data["state"][name]
            if not isinstance(table, dict) or "" in table:
                raise ProtocolError(f"invalid snapshot state table: {name}")
    elif kind == "error" and (not isinstance(message["message"], str) or not message["message"]):
        raise ProtocolError("error message must be a nonempty string")


def encode(message: dict, *, steam_pose=False) -> bytes:
    """Validate and encode one message as UTF-8 JSON without transport framing."""
    try:
        _check_message(message, steam_pose=steam_pose)
        return json.dumps(message, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("message cannot be encoded as UTF-8 JSON") from exc


def decode(data: bytes, *, steam_pose=False) -> dict:
    """Decode one UTF-8 JSON message and check its envelope and payload shape."""
    if not isinstance(data, bytes):
        raise ProtocolError("expected a UTF-8 byte string")
    try:
        message = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        _check_message(message, steam_pose=steam_pose)
        return message
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("invalid UTF-8 JSON message") from exc
