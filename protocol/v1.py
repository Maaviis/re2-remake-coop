"""Reference codec for the proposed version 1 gameplay message envelope."""

import json
import math
import re


VERSION = 1
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


def _check_message(message):
    if not isinstance(message, dict):
        raise ProtocolError("expected a message object")
    version = message.get("version")
    if type(version) is not int or version != VERSION:
        raise ProtocolError("unsupported protocol version")
    kind = message.get("type")
    if not isinstance(kind, str) or kind not in MESSAGE_FIELDS:
        raise ProtocolError("unknown message type")
    fields = MESSAGE_FIELDS[kind]
    if kind == "hello" and message.get("heartbeat") is True:
        fields = fields | {"heartbeat"}
    _check_fields(message, fields, kind)
    _check_json(message)

    if kind in ("ping", "pong"):
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


def encode(message: dict) -> bytes:
    """Validate and encode one message as UTF-8 JSON without transport framing."""
    try:
        _check_message(message)
        return json.dumps(message, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("message cannot be encoded as UTF-8 JSON") from exc


def decode(data: bytes) -> dict:
    """Decode one UTF-8 JSON message and check its envelope and payload shape."""
    if not isinstance(data, bytes):
        raise ProtocolError("expected a UTF-8 byte string")
    try:
        message = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        _check_message(message)
        return message
    except ProtocolError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("invalid UTF-8 JSON message") from exc
