"""Read-only native save comparison before a shared load; never loads or saves."""

from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import time

from load_witness import _read_json
from save_catalog import IDENTITY_FIELDS, SaveCatalog, validate_reference
from save_protection import read_save_protection
from sync_model import state_digest


MAX_SAVE_BYTES = 32 * 1024 * 1024
ACK_LEASE = 5
CHECK_INTERVAL = 1
STAGED_LOAD_AGE = 20
TOKEN = re.compile(r"[0-9a-f]{32}")
DIGEST = re.compile(r"[0-9a-f]{64}")
REASONS = {"", "selection_changed", "local_source_unavailable", "local_file_changed",
           "guest_source_unavailable", "guest_file_mismatch", "guest_ack_expired", "cancelled",
           "start_window_expired"}


def validate_check(value, *, revision, eligible):
    if value is None:
        return
    required = {"attempt_id", "revision", "save_digest", "phase", "reason"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | {"admission", "start"}:
        raise ValueError("invalid shared load check fields")
    if (not isinstance(value["attempt_id"], str) or not TOKEN.fullmatch(value["attempt_id"])
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= revision
            or not isinstance(value["save_digest"], str) or not DIGEST.fullmatch(value["save_digest"])
            or not isinstance(value["phase"], str) or value["phase"] not in ("checking", "prepared", "starting", "failed")
            or not isinstance(value["reason"], str) or value["reason"] not in REASONS):
        raise ValueError("invalid shared load check")
    if "admission" in value and (type(value["admission"]) is not int or value["admission"] != 1):
        raise ValueError("invalid shared load admission version")
    if value["phase"] == "starting":
        start = value.get("start")
        if (value.get("admission") != 1 or not isinstance(start, dict)
                or start.keys() != {"H", "G", "guest_ack_sequence"}
                or not all(isinstance(start[role], str) and TOKEN.fullmatch(start[role]) for role in ("H", "G"))
                or start["H"] == start["G"] or type(start["guest_ack_sequence"]) is not int
                or not 1 <= start["guest_ack_sequence"] <= 2**53 - 1):
            raise ValueError("invalid shared load start decision")
    elif "start" in value:
        raise ValueError("shared load start requires the starting phase")
    if value["phase"] != "failed":
        if not eligible or value["revision"] != revision or value["reason"]:
            raise ValueError("shared load check requires the ready selection")
    elif not value["reason"]:
        raise ValueError("failed shared load check needs a reason")


def validate_ack(value):
    required = {"version", "type", "session_id", "revision", "attempt_id", "sequence", "save_digest", "accepted"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | {"stage_id"}:
        raise ValueError("invalid shared load acknowledgment fields")
    if (type(value["version"]) is not int or value["version"] != 1 or value["type"] != "lobby_load_ack"
            or not isinstance(value["session_id"], str) or not 0 < len(value["session_id"]) <= 128
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2**53 - 1
            or not isinstance(value["attempt_id"], str) or not TOKEN.fullmatch(value["attempt_id"])
            or type(value["sequence"]) is not int or not 1 <= value["sequence"] <= 2**53 - 1
            or type(value["accepted"]) is not bool
            or (value["save_digest"] is not None and (not isinstance(value["save_digest"], str)
                                                      or not DIGEST.fullmatch(value["save_digest"])))
            or value["accepted"] and value["save_digest"] is None):
        raise ValueError("invalid shared load acknowledgment")
    if "stage_id" in value and (not value["accepted"] or not isinstance(value["stage_id"], str)
                                or not TOKEN.fullmatch(value["stage_id"])):
        raise ValueError("invalid staged load acknowledgment")


def read_staged_load(data, message, role, game_pid, membership):
    """Read a native acknowledgment of the current, still-pending local command."""
    check = message["data"].get("load_check")
    if (not check or check.get("admission") != 1 or check["phase"] not in ("prepared", "starting")
            or membership is None or type(game_pid) is not int):
        return None
    now = time.time()
    try:
        guard = _read_json(data / "re2_coop_save_guard.json")
        policy = _read_json(data / "re2_coop_save_policy.json", max_bytes=4096)
        if not isinstance(guard, dict) or not isinstance(policy, dict):
            return None
        run = guard.get("guard_run_id")
        scope = {"game_pid": game_pid, "role": role, "membership": membership,
                 "session_id": message["session_id"], "guard_run_id": run,
                 **{field: check[field] for field in ("attempt_id", "revision", "save_digest")}}
        expected = state_digest(scope)[:32]
        selected = message["data"]["save_ref"]
        at = policy.get("at")
        if (type(policy.get("schema")) is not int or policy["schema"] != 3
                or policy.get("load") is not True or policy.get("lobby_load") != scope
                or policy.get("id") != expected or type(at) is not int or not 0 <= now - at <= STAGED_LOAD_AGE
                or policy.get("reference") != {field: selected[field] for field in IDENTITY_FIELDS}
                or guard.get("staged_load") != {"id": expected, "requested_at": at}
                or type(guard.get("schema")) is not int or guard["schema"] != 1 or guard.get("active") is not True
                or type(guard.get("hooks")) is not int or guard["hooks"] != 26
                or type(guard.get("at")) is not int or not 0 <= now - guard["at"] <= 3
                or not isinstance(run, str) or not 0 < len(run) <= 128
                or type(guard.get("denied_loads")) is not int or guard["denied_loads"] != 0
                or guard.get("writes") not in (None, {}) or guard.get("protection_active") is not True):
            return None
        protection = read_save_protection(data, now=now)
        if protection["game_pid"] == game_pid and guard.get("protection") == policy.get("protection") == protection:
            return expected
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


class NativeSaveSource:
    def __init__(self, data, save_directory, *, allow_date):
        directory = Path(save_directory)
        if not directory.is_absolute() or not directory.is_dir() or allow_date is None:
            raise ValueError("absolute native save directory and explicit allowed date required")
        self.supplied_directory = directory
        self.directory = directory.resolve(strict=True)
        self.catalog = SaveCatalog(Path(data) / "re2_coop_save_catalog.json", allow_date=allow_date)

    def fingerprint(self, reference):
        validate_reference(reference)
        local = self.catalog.select(f"scenario:{reference['slot_id']}")
        # Labels may be localized. Compare native identity and actual file bytes.
        if any(local[field] != reference[field] for field in IDENTITY_FIELDS):
            raise ValueError("selected native save is not available locally")
        path = self.directory / f"data{reference['slot_id']:03d}Slot.bin"
        if path.is_symlink() or path.resolve(strict=True).parent != self.directory:
            raise ValueError("native save must be an ordinary file inside the selected directory")
        digest = sha256()
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SAVE_BYTES:
                raise ValueError("native save file size or type is unsupported")
            total = 0
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > MAX_SAVE_BYTES:
                    raise ValueError("native save grew during comparison")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        current = path.stat()
        # Windows exposes different ctime semantics through stat and fstat.
        # Compare ctime within the same handle, not between those APIs.
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if (total != before.st_size or before.st_ctime_ns != after.st_ctime_ns
                or path.is_symlink() or path.resolve(strict=True).parent != self.directory
                or any(getattr(before, field) != getattr(sample, field)
                       for sample in (after, current) for field in fields)):
            raise ValueError("native save changed during comparison")
        # Revalidate the catalog lease/identity after hashing; no result survives its expiry.
        check = self.catalog.select(f"scenario:{reference['slot_id']}")
        if check != local:
            raise ValueError("native save metadata changed during comparison")
        return digest.hexdigest()
