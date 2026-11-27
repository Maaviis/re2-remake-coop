"""Read RE2's exported scenario-save metadata; this module never loads a save."""

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import time

from sync_model import state_digest


MAX_AGE = 3
MAX_BYTES = 131072
MAX_TICKS = 3155378975999999999
REFERENCE_FIELDS = {"available", "mode", "slot_id", "timestamp", "scenario", "label", "difficulty_label", "metadata_digest"}
IDENTITY_FIELDS = ("mode", "slot_id", "timestamp", "scenario")


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _text(value, limit):
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError("invalid save metadata text")
    return value


def saved_time(timestamp):
    if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,19}", timestamp):
        raise ValueError("invalid save metadata timestamp")
    ticks = int(timestamp)
    if not 0 < ticks <= MAX_TICKS:
        raise ValueError("invalid save metadata timestamp")
    # The native getter reports calendar ticks; its timezone kind is not exposed.
    return datetime.min + timedelta(microseconds=ticks // 10)


def validate_reference(value):
    if not isinstance(value, dict) or set(value) != REFERENCE_FIELDS:
        raise ValueError("invalid save reference fields")
    if (value["available"] is not True or type(value["mode"]) is not int or value["mode"] != 1
            or not _integer(value["slot_id"], 0, 20) or not _integer(value["scenario"], 0, 3)):
        raise ValueError("invalid scenario save reference")
    saved_time(value["timestamp"])
    _text(value["label"], 512)
    _text(value["difficulty_label"], 256)
    if not isinstance(value["metadata_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["metadata_digest"]):
        raise ValueError("invalid save metadata digest")


def reference_identity_digest(reference):
    return state_digest({field: reference[field] for field in IDENTITY_FIELDS})


def _validate(value):
    if not isinstance(value, dict) or set(value) != {
            "schema", "source", "tdb", "mode", "run_id", "sequence", "observed_at", "available", "reason", "entries"}:
        raise ValueError("invalid save catalog fields")
    if (type(value["schema"]) is not int or value["schema"] != 1 or value["source"] != "re2"
            or type(value["tdb"]) is not int or value["tdb"] != 70
            or type(value["mode"]) is not int or value["mode"] != 1
            or not _integer(value["observed_at"], 1, 2**53 - 1)
            or not _integer(value["sequence"], 1, 2**53 - 1)
            or not isinstance(value["run_id"], str) or not 0 < len(value["run_id"]) <= 128
            or type(value["available"]) is not bool):
        raise ValueError("unsupported or malformed save catalog")
    _text(value["reason"], 128)
    if not isinstance(value["entries"], list) or len(value["entries"]) > 21:
        raise ValueError("invalid save catalog entries")
    if not value["available"] and value["entries"]:
        raise ValueError("unavailable catalog contains saves")
    seen = set()
    for entry in value["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"slot_id", "timestamp", "scenario", "title", "subtitle", "detail"}:
            raise ValueError("invalid save catalog entry")
        if (not _integer(entry["slot_id"], 0, 20) or entry["slot_id"] in seen
                or not _integer(entry["scenario"], 0, 3)):
            raise ValueError("invalid or repeated scenario save")
        seen.add(entry["slot_id"])
        saved_time(entry["timestamp"])
        for field, limit in (("title", 256), ("subtitle", 512), ("detail", 2048)):
            _text(entry[field], limit)
        _text((entry["detail"].splitlines() or [""])[0], 256)


class SaveCatalog:
    def __init__(self, path, *, allow_date=None, new_game_only=False):
        self.path = Path(path)
        self.allow_date = date.fromisoformat(allow_date) if allow_date is not None else None
        self.accepted = None
        self.new_game_only = new_game_only
        self.view = {"available": False, "reason": "catalog_unavailable", "entries": []}

    def snapshot(self, *, now=None):
        if self.new_game_only:
            self.view = {"available": True, "reason": "no_eligible_saves", "entries": []}
            return deepcopy(self.view)
        now = time.time() if now is None else now
        try:
            if self.path.stat().st_size > MAX_BYTES:
                raise ValueError("catalog exceeds the byte limit")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("entries") is None and "entries" in value:
                value["entries"] = []  # REFramework serializes an empty Lua sequence as null.
            _validate(value)
            if not 0 <= now - value["observed_at"] <= MAX_AGE:
                raise ValueError("expired catalog")
            previous = self.accepted
            if previous is not None and value["run_id"] == previous["run_id"]:
                if value["sequence"] < previous["sequence"]:
                    raise ValueError("catalog sequence rollback")
                if value["sequence"] == previous["sequence"] and value != previous:
                    raise ValueError("catalog changed without a new sequence")
            self.accepted = deepcopy(value)
        except (OSError, ValueError, RecursionError):
            # An in-progress native JSON write does not renew or erase a valid lease.
            pass
        value = self.accepted
        if value is None or not 0 <= now - value["observed_at"] <= MAX_AGE:
            self.view = {"available": False, "reason": "catalog_unavailable", "entries": []}
        elif not value["available"]:
            self.view = {"available": False, "reason": value["reason"], "entries": []}
        else:
            entries = []
            for entry in value["entries"]:
                stamp = saved_time(entry["timestamp"])
                if self.allow_date is not None and stamp.date() != self.allow_date:
                    continue
                difficulty_label = (entry["detail"].splitlines() or [""])[0]
                _text(difficulty_label, 256)
                entries.append({"key": f"scenario:{entry['slot_id']}", "saved_at": stamp.isoformat(sep=" "),
                                "reference": {"available": True, "mode": 1, "slot_id": entry["slot_id"],
                                    "timestamp": entry["timestamp"], "scenario": entry["scenario"],
                                    "label": entry["subtitle"], "difficulty_label": difficulty_label,
                                    "metadata_digest": state_digest(entry)},
                                "detail": entry["detail"]})
            entries.sort(key=lambda entry: entry["reference"]["slot_id"])
            self.view = {"available": True, "reason": "ok" if entries else "no_eligible_saves", "entries": entries}
        return deepcopy(self.view)

    def select(self, key):
        for entry in self.snapshot()["entries"]:
            if entry["key"] == key:
                return deepcopy(entry["reference"])
        raise ValueError("select an available RE2 save from the current catalog")
