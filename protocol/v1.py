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
    } if steam_pose else {}
    if not isinstance(kind, str) or kind not in MESSAGE_FIELDS.keys() | lobby_fields.keys():
        raise ProtocolError("unknown message type")
    fields = (MESSAGE_FIELDS | lobby_fields)[kind]
    if steam_pose and kind in ("hello", "snapshot", "campaign_pose_capability"):
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ProtocolError("invalid Steam pose request_id")
        fields = fields | {"request_id"}
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
        if "save_identity" in message:
            identity = message["save_identity"]
            if message.get("value") is not True or not isinstance(identity, str) or not DIGEST.fullmatch(identity):
                raise ProtocolError("invalid lobby save identity")
            fields = fields | {"save_identity"}
        if "campaign_consent" in message:
            if message["campaign_consent"] is not True or "save_identity" not in message:
                raise ProtocolError("campaign consent requires ready native save identity")
            fields = fields | {"campaign_consent"}
    elif steam_pose and kind == "lobby_load_ack" and "stage_id" in message:
        fields = fields | {"stage_id"}
    elif kind == "hello" and message.get("heartbeat") is True:
        fields = fields | {"heartbeat"}
    _check_fields(message, fields, kind)
    _check_json(message)

    if kind == "lobby_state":
        from lobby_sync import validate_state
        _check_authority(message, 1)
        validate_state(message["data"])
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
