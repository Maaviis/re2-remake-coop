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


def validate_checkpoint(selection, *, metadata=False):
    fields = {'namespace', 'digest'}
    if metadata:
        fields |= {'scenario', 'difficulty', 'saved_at'}
    if (not isinstance(selection, dict) or set(selection) != fields
            or not isinstance(selection.get('namespace'), str) or not TOKEN.fullmatch(selection['namespace'])
            or not isinstance(selection.get('digest'), str) or not DIGEST.fullmatch(selection['digest'])):
        raise ValueError('invalid native checkpoint selection')
    if metadata:
        from datetime import datetime
        if (type(selection['scenario']) is not int or selection['scenario'] not in (0, 1)
                or type(selection['difficulty']) is not int or selection['difficulty'] not in (0, 1, 2)
                or not isinstance(selection['saved_at'], str)):
            raise ValueError('invalid native checkpoint metadata')
        stamp = datetime.fromisoformat(selection['saved_at'])
        if stamp.tzinfo is not None or stamp.isoformat(sep=' ', timespec='seconds') != selection['saved_at']:
            raise ValueError('invalid native checkpoint calendar')


def checkpoint_save_reference(reference):
    """Adapt a verified native slot-0 receipt for the existing load witnesses."""
    from save_catalog import saved_time
    if (not isinstance(reference, dict) or set(reference) != set(IDENTITY_FIELDS)
            or type(reference['mode']) is not int or reference['mode'] != 1
            or type(reference['slot_id']) is not int or reference['slot_id'] != 0
            or type(reference['scenario']) is not int or reference['scenario'] not in (0, 1)):
        raise ValueError('invalid native checkpoint reference')
    saved_time(reference['timestamp'])
    result = {**reference, 'available': True, 'label': '', 'difficulty_label': '',
              'metadata_digest': state_digest({'checkpoint_reference': reference})}
    validate_reference(result)
    return result


def validate_check(value, *, revision, eligible):
    if value is None:
        return
    required = {"attempt_id", "revision", "save_digest", "phase", "reason"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | {"admission", "start", "campaign_start", "checkpoint_version"}:
        raise ValueError("invalid shared load check fields")
    if (not isinstance(value["attempt_id"], str) or not TOKEN.fullmatch(value["attempt_id"])
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= revision
            or not isinstance(value["save_digest"], str) or not DIGEST.fullmatch(value["save_digest"])
            or not isinstance(value["phase"], str) or value["phase"] not in ("checking", "prepared", "starting", "failed")
            or not isinstance(value["reason"], str) or value["reason"] not in REASONS):
        raise ValueError("invalid shared load check")
    if "admission" in value and (type(value["admission"]) is not int or value["admission"] != 1):
        raise ValueError("invalid shared load admission version")
    if "campaign_start" in value and (value["campaign_start"] is not True or value.get("admission") != 1):
        raise ValueError("invalid protected campaign start")
    if 'checkpoint_version' in value and (
            type(value['checkpoint_version']) is not int or value['checkpoint_version'] != 1
            or value.get('admission') != 1 or value.get('campaign_start') is not True):
        raise ValueError('invalid checkpoint load admission version')
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
        lobby = message['data']
        new_game = lobby.get('new_game')
        checkpoint = lobby['settings'].get('coop_checkpoint')
        staged = {'id': expected, 'requested_at': policy.get('at')}
        if checkpoint is not None:
            validate_checkpoint(checkpoint, metadata=True)
            compact = {key: checkpoint[key] for key in ('namespace', 'digest')}
            reference = policy.get('reference')
            checkpoint_save_reference(reference)
            preparation = policy.get('preparation_id')
            if (policy.get('schema') != 5 or policy.get('checkpoint') != compact or 'new_game' in policy
                    or not isinstance(preparation, str) or not TOKEN.fullmatch(preparation)
                    or type(check.get('checkpoint_version')) is not int or check['checkpoint_version'] != 1
                    or check.get('campaign_start') is not True
                    or check['save_digest'] != compact['digest'] or reference['scenario'] != checkpoint['scenario']
                    or guard.get('checkpoint_supported') is not True or guard.get('runtime_protection') is not True
                    or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 0):
                return None
            workspace = _read_json(data/'re2_coop_checkpoint_workspace.json', max_bytes=8192)
            if (not isinstance(workspace, dict) or workspace.get('phase') != 'ready'
                    or type(workspace.get('at')) is not int or not 0 <= now-workspace['at'] <= 3
                    or workspace.get('request_id') != preparation or workspace.get('selection') != compact
                    or workspace.get('native_reference') != reference or workspace.get('guard_run_id') != run
                    or workspace.get('lobby_revision') != check['revision']
                    or workspace.get('protection') != policy.get('protection')
                    or workspace.get('scope') != {key: scope[key] for key in ('game_pid', 'role', 'membership', 'session_id')}):
                return None
            staged.update(checkpoint=compact, preparation_id=preparation, reference=reference)
        elif new_game is not None:
            from lobby_sync import validate_new_game

            validate_new_game(new_game)
            if (policy.get('schema') != 4 or policy.get('new_game') != new_game or 'reference' in policy
                    or lobby.get('save_slot') is not None or 'save_ref' in lobby or check.get('campaign_start') is not True
                    or state_digest({'new_game': new_game}) != check['save_digest'] or guard.get('new_game_supported') is not True
                    or type(guard.get('allowed_load_calls')) is not int or guard['allowed_load_calls'] != 0):
                return None
        elif (policy.get('schema') != 3 or 'new_game' in policy
                or policy.get('reference') != {field: lobby['save_ref'][field] for field in IDENTITY_FIELDS}):
            return None
        at = policy.get("at")
        if (type(policy.get("schema")) is not int
                or policy.get("load") is not True or policy.get("lobby_load") != scope
                or policy.get("id") != expected or type(at) is not int or not 0 <= now - at <= STAGED_LOAD_AGE
                or guard.get("staged_load") != staged
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
    def __init__(self, data, save_directory, *, allow_date, managed=False, campaign_binding=None):
        directory = Path(save_directory)
        if not directory.is_absolute() or not directory.is_dir() or (allow_date is None and not managed and not campaign_binding):
            raise ValueError("absolute native save directory and explicit allowed date required")
        self.campaign_binding = campaign_binding
        self.data = Path(data)
        if campaign_binding is not None:
            if managed or allow_date is not None or not TOKEN.fullmatch(campaign_binding.get('campaign_namespace', '')):
                raise ValueError("invalid direct campaign binding")
        elif managed:
            from campaign_save_copy import check_managed_save

            check_managed_save(directory, required=True)
        self.supplied_directory = directory
        self.directory = directory.resolve(strict=True)
        self.catalog = SaveCatalog(self.data / "re2_coop_save_catalog.json", allow_date=allow_date,
                                  new_game_only=campaign_binding is not None)

    def resolve_new_game(self, selection):
        from campaign_save_copy import check_managed_save
        from lobby_sync import validate_new_game

        validate_new_game(selection)
        if self.campaign_binding is None:
            check_managed_save(self.supplied_directory, required=True)
        else:
            from readonly_save_control import read_active_guard
            guard = read_active_guard(self.data, protected=True, runtime_directory=self.supplied_directory)
            if (guard['protection'] != self.campaign_binding
                    or guard.get('campaign_mount_ready') != self.campaign_binding['campaign_namespace']):
                raise ValueError('Der Koop-Ordner gehört nicht mehr zur aktiven Kampagne.')
        return state_digest({'new_game': selection})

    def checkpoint_receipt(self, selection, pipe):
        from checkpoint_workspace import read_prepared_checkpoint
        validate_checkpoint(selection, metadata=isinstance(selection, dict) and set(selection) != {'namespace', 'digest'})
        compact = {key: selection[key] for key in ('namespace', 'digest')}
        if self.campaign_binding is None or pipe.game_pid != self.campaign_binding['game_pid']:
            raise ValueError('checkpoint loading requires the current native campaign mount')
        receipt = read_prepared_checkpoint(self.data, pipe, self.supplied_directory, compact,
                                           expected_choice=selection if len(selection) == 5 else None)
        if receipt['protection'] != self.campaign_binding:
            raise ValueError('checkpoint preparation belongs to another native mount')
        return receipt

    def resolve_checkpoint(self, selection):
        from steam_pose_bridge import SteamPipe
        if self.campaign_binding is None:
            raise ValueError('checkpoint loading requires a native campaign mount')
        self.checkpoint_receipt(selection, SteamPipe(self.campaign_binding['game_pid']))
        return selection['digest']

    def fingerprint(self, reference):
        validate_reference(reference)
        local = self.catalog.select(f"scenario:{reference['slot_id']}")
        # Labels may be localized. Compare native identity and actual file bytes.
        if any(local[field] != reference[field] for field in IDENTITY_FIELDS):
            raise ValueError("selected native save is not available locally")
        name = 'data000.bin' if reference['slot_id'] == 0 else f"data{reference['slot_id']:03d}Slot.bin"
        path = self.directory / name
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
