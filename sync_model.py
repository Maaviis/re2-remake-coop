"""Transportunabhängiger, hostautoritärer Zustandskern für einen RE2-Koop-Prototyp."""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import uuid


def state_digest(state):
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ResyncRequired(ValueError):
    """A verified replica needs a new authoritative snapshot."""


@dataclass
class Replica:
    sequence: int = 0
    state: dict = field(default_factory=lambda: {
        "players": {}, "enemies": {}, "doors": {}, "puzzles": {},
        "items": {}, "inventories": {}, "flags": {}, "actions": {},
        "damage": {}, "scripts": {}, "cutscene": None,
    })
    session_id: str | None = None

    def snapshot(self):
        return {"sequence": self.sequence, "state": deepcopy(self.state),
                "digest": state_digest(self.state), "session_id": self.session_id}

    def restore(self, snapshot):
        incoming_session = snapshot["session_id"]
        if not incoming_session or (self.session_id is not None and incoming_session != self.session_id):
            raise ValueError("session mismatch")
        if state_digest(snapshot["state"]) != snapshot["digest"]:
            raise ValueError("snapshot digest mismatch")
        if snapshot["sequence"] < self.sequence:
            raise ValueError("stale snapshot")
        self.sequence = snapshot["sequence"]
        self.state = deepcopy(snapshot["state"])
        self.session_id = incoming_session

    def apply(self, event):
        incoming_session = event["session_id"]
        if not incoming_session or (self.session_id is not None and incoming_session != self.session_id):
            raise ValueError("session mismatch")
        number = event["sequence"]
        if number <= self.sequence:
            return False
        if number != self.sequence + 1:
            raise ResyncRequired("sequence gap: request a host snapshot")
        if not isinstance(event.get("digest"), str):
            raise ValueError("event digest required: request a host snapshot")
        next_state = self._transition(event["kind"], event.get("target"), event.get("value"))
        if state_digest(next_state) != event["digest"]:
            raise ResyncRequired("event digest mismatch: request a host snapshot")
        self.state = next_state
        self.sequence = number
        self.session_id = incoming_session
        return True

    def _transition(self, kind, target, value):
        buckets = {
            "player": "players", "enemy": "enemies", "door": "doors",
            "puzzle": "puzzles", "item": "items", "inventory": "inventories",
            "flag": "flags", "action": "actions", "damage": "damage",
            "script": "scripts",
        }
        next_state = deepcopy(self.state)
        if kind in buckets:
            if target is None:
                raise ValueError("target required")
            next_state[buckets[kind]][target] = deepcopy(value)
        elif kind == "cutscene":
            next_state["cutscene"] = deepcopy(value)
        else:
            raise ValueError(f"unknown event kind: {kind}")
        return next_state


class Host(Replica):
    def __init__(self, session_id=None):
        super().__init__(session_id=session_id or uuid.uuid4().hex)

    def emit(self, kind, target=None, value=None, *, validate=None):
        event = {"sequence": self.sequence + 1, "kind": kind,
                 "target": target, "value": deepcopy(value),
                 "session_id": self.session_id}
        next_state = self._transition(kind, target, event["value"])
        event["digest"] = state_digest(next_state)
        if validate is not None:
            validate(event, {"sequence": event["sequence"], "session_id": self.session_id,
                             "state": next_state, "digest": event["digest"]})
        self.apply(event)
        return event

